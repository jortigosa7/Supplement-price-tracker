"""
scrapers/hsn.py — Scraper para HSN Store (hsnstore.com)

El grid de productos usa SSR (HTML estático del servidor). SpotlerSearch inyecta
el mismo grid vía XHR pero el HTML original ya contiene los form.product-item,
por lo que NO necesitamos Playwright para el listado.

Las páginas de detalle también se sirven en SSR: rating (JSON-LD), tabla nutricional
(div.nutritionalTable), servings (texto) y flavors (select anónimo) son extraíbles
con requests + BeautifulSoup. Las páginas se cachean 7 días.
"""

import json
import re
import time

import requests
from bs4 import BeautifulSoup

from .base import HEADERS, hacer_peticion, producto_base
from .detail_cache import get_cached, save_cache

TIENDA   = "HSN"
BASE_URL = "https://www.hsnstore.com"
DELAY    = 2  # segundos entre peticiones

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/whey"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/nutricion-deportiva/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/nutricion-deportiva/aminoacidos/bcaa-s-ramificados"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/nutricion-deportiva/pre-entrenamiento"},
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _extraer_peso_kg_desde_select(soup: BeautifulSoup) -> float | None:
    """
    El select anónimo (sin id) contiene opciones con nombre completo + peso + sabor,
    ej. "EVOLATE 2.0 2Kg CHOCOLATE". Extrae el peso de la primera opción con unidad.
    """
    for sel in soup.find_all("select"):
        if sel.get("id"):
            continue  # saltar selects con id (selectProductSimple y otros)
        opts = [o.get_text(strip=True) for o in sel.find_all("option") if o.get_text(strip=True)]
        if not opts:
            continue
        m = re.search(r"(\d+[\.,]?\d*)\s*(kg|g)\b", opts[0], re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", "."))
            unit = m.group(2).lower()
            if unit == "g":
                val /= 1000
            return round(val, 3)
    return None


def _extraer_sabores_desde_select(soup: BeautifulSoup, nombre_producto: str) -> list[str]:
    """
    Extrae los sabores del select anónimo.
    Cada opción tiene formato "NOMBRE_PRODUCTO Xkg SABOR".
    Elimina el prefijo de nombre+peso para obtener solo el sabor.
    """
    nombre_norm = re.sub(r"\s+", " ", nombre_producto.strip().lower())
    for sel in soup.find_all("select"):
        if sel.get("id"):
            continue
        opts = [o.get_text(strip=True) for o in sel.find_all("option") if o.get_text(strip=True)]
        if not opts or len(opts) < 2:
            continue
        # Verificar que las opciones tienen unidades de peso (son las correctas)
        if not any(re.search(r"\d+\s*(kg|g)\b", o, re.I) for o in opts):
            continue
        sabores = []
        for opt in opts:
            # Extraer la parte después del peso: "NOMBRE 2Kg SABOR" → "SABOR"
            m = re.search(r"\d+[\.,]?\d*\s*(?:kg|g)\s+(.+)", opt, re.IGNORECASE)
            if m:
                sabor = m.group(1).strip()
                if sabor and sabor not in sabores:
                    sabores.append(sabor)
        if sabores:
            return sabores
    return []


def _scrape_detalle(url: str, nombre: str) -> dict:
    """
    Visita la página de detalle de un producto HSN (con caché de 7 días) y extrae:
    - store_rating, store_rating_count, store_rating_url  (JSON-LD Product)
    - servings_per_container  (texto "Servicios: X")
    - serving_size_g          (texto "Tamaño de la dosis: ... (Xg)")
    - protein_per_serving_g   (tabla nutritionalTable, fila Proteínas, col por_servicio)
    - flavors_available       (select anónimo con peso+sabor)
    - sweetener_free          (nombre del producto)
    - peso_kg                 (select anónimo)

    Los campos no encontrados se omiten del dict devuelto (permanecen null en build.py).
    """
    html = get_cached("hsn", url)
    if html is None:
        r = hacer_peticion(url)
        if not r or r.status_code != 200:
            return {}
        html = r.text
        save_cache("hsn", url, html)

    soup = BeautifulSoup(html, "html.parser")
    enrichment: dict = {}

    # ── Rating desde JSON-LD ────────────────────────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if data.get("@type") == "Product":
                agg = data.get("aggregateRating", {})
                rv = agg.get("ratingValue")
                rc = agg.get("reviewCount")
                if rv:
                    enrichment["store_rating"] = round(float(rv), 2)
                if rc:
                    enrichment["store_rating_count"] = int(rc)
                    enrichment["store_rating_url"] = url
                break
        except Exception:
            pass

    # ── Servings per container ("Servicios: 40") ────────────────────────────
    m = re.search(r"Servicios:\s*(\d+)", html)
    if m:
        enrichment["servings_per_container"] = int(m.group(1))

    # ── Serving size ("Tamaño de la dosis: 2 dosificadores de 50ml (50g)") ──
    m = re.search(r"Tama[ñn]o de la dosis[^(]*\((\d+(?:[.,]\d+)?)g\)", html, re.IGNORECASE)
    if m:
        enrichment["serving_size_g"] = float(m.group(1).replace(",", "."))

    # ── Protein per serving desde div.nutritionalTable ──────────────────────
    # La página es ~2.4 MB, lo que hace que BS4 pierda texto en tablas internas.
    # Usamos regex directamente en el HTML crudo para mayor fiabilidad.
    # Estrategia: encontrar el nutritionalTable más cercano al texto "Servicios:"
    # (que identifica la sección del producto), luego extraer la fila Proteínas.
    serv_pos = html.find("Servicios:")
    if serv_pos == -1:
        serv_pos = 0
    nt_pos = html.find("nutritionalTable", max(0, serv_pos - 200))
    if nt_pos != -1:
        nt_section = html[nt_pos : nt_pos + 10000]
        # Patrón: "Proteínas" (label) → td con x-show=por_servicio → valor Xg
        m2 = re.search(
            r"Prote[íi]nas.*?por_servicio['\"].*?>\s*([\d,]+)\s*g\s*<",
            nt_section,
            re.DOTALL | re.IGNORECASE,
        )
        if m2:
            enrichment["protein_per_serving_g"] = float(m2.group(1).replace(",", "."))

    # ── Flavors desde select anónimo ────────────────────────────────────────
    sabores = _extraer_sabores_desde_select(soup, nombre)
    if sabores:
        enrichment["flavors_available"] = sabores

    # ── Sweetener-free: detectado desde el nombre del producto ──────────────
    # (más fiable que buscar texto en toda la página, que incluye nav/links)
    enrichment["sweetener_free"] = bool(
        re.search(r"sin edulcorantes", nombre, re.IGNORECASE)
    )

    # ── Peso del producto (para nombre_con_peso) ────────────────────────────
    peso_kg = _extraer_peso_kg_desde_select(soup)
    if peso_kg:
        enrichment["_peso_kg"] = peso_kg  # prefijado _ para no confundir con campo schema

    return enrichment


def _talla_str(peso_kg: float) -> str:
    """0.5 → '500g',  1.0 → '1kg',  2.27 → '2.27kg'"""
    if peso_kg < 1:
        return f"{round(peso_kg * 1000)}g"
    return f"{peso_kg:g}kg"


# ── Scraper principal ─────────────────────────────────────────────────────────

def scrape(debug: bool = False) -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    productos_raw: list[dict] = []

    # ── Paso 1: listados de categoría (requests + BeautifulSoup) ─────────────
    for cat in CATEGORIAS:
        print(f"\n  Categoria: {cat['nombre']}")
        url_actual = cat["url"]
        pagina = 1

        while url_actual:
            print(f"  Página {pagina}: {url_actual}")
            r = hacer_peticion(url_actual)
            if not r:
                print("  Sin respuesta, abortando esta categoría")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("form.product-item")

            if not items:
                print("  Sin productos en esta página")
                break

            nuevos = 0
            for item in items:
                link = item.select_one("a.product-item-link")
                if not link:
                    continue
                nombre = link.get_text(strip=True)
                url_prod = link.get("href", "")
                if not nombre or not url_prod:
                    continue

                # Precio: HSN muestra precio especial en span.special-price .price
                precio_el = (
                    item.select_one("span.special-price .price")
                    or item.select_one('[data-price-type="finalPrice"] .price')
                    or item.select_one(".price-final_price .price")
                    or item.select_one("span.price")
                )
                precio = precio_el.get_text(strip=True) if precio_el else "N/A"

                # Imagen (lazy-loaded: data-src antes que src)
                img = item.select_one("img.product-image-photo")
                imagen_url = None
                if img:
                    src = img.get("data-src") or img.get("src") or ""
                    if src.startswith("http"):
                        imagen_url = src

                productos_raw.append({
                    "nombre":     nombre,
                    "precio":     precio,
                    "categoria":  cat["nombre"],
                    "url":        url_prod,
                    "imagen_url": imagen_url,
                })
                nuevos += 1

            print(f"  +{nuevos} productos (acumulado: {len(productos_raw)})")

            if debug:
                break

            # Paginación: <a rel="next"> (Magento2 usa ?p=2)
            next_link = soup.select_one("a[rel='next']")
            url_actual = next_link.get("href") if next_link else None
            pagina += 1
            if url_actual:
                time.sleep(DELAY)

        time.sleep(DELAY)

    if debug:
        print(f"\n  [DEBUG] {len(productos_raw)} productos encontrados en listados")
        return []

    # ── Paso 2: páginas de detalle (enriquecimiento + peso) ──────────────────
    print(f"\n  Enriqueciendo {len(productos_raw)} productos (detalle + caché 7 días)...")
    productos: list[dict] = []
    stats = {"cached": 0, "fetched": 0, "errors": 0}

    for i, d in enumerate(productos_raw):
        from .detail_cache import get_cached as _gc  # lazy import para test unitario
        cached_check = _gc("hsn", d["url"])
        if cached_check is not None:
            stats["cached"] += 1
        else:
            stats["fetched"] += 1

        enrichment = _scrape_detalle(d["url"], d["nombre"])
        if not enrichment and cached_check is None:
            stats["errors"] += 1

        # Construir nombre con peso si el select lo proporcionó
        nombre_final = d["nombre"]
        peso_kg = enrichment.pop("_peso_kg", None)
        if peso_kg and not re.search(r"\d+[\.,]?\d*\s*(kg|g)\b", nombre_final, re.I):
            nombre_final = f"{nombre_final} {_talla_str(peso_kg)}"

        prod = producto_base(
            nombre_final,
            d["precio"],
            "",           # marca: matching.py la extrae
            d["categoria"],
            TIENDA,
            d["url"],
            d.get("imagen_url"),
        )
        prod.update(enrichment)  # añade todos los campos de enriquecimiento
        productos.append(prod)

        if (i + 1) % 10 == 0:
            print(f"  ... {i+1}/{len(productos_raw)} (caché:{stats['cached']} / fetch:{stats['fetched']} / err:{stats['errors']})")
        time.sleep(1)

    print(f"\n  Total HSN: {len(productos)} productos")
    print(f"  Detalle: {stats['fetched']} fetcheados, {stats['cached']} desde caché, {stats['errors']} errores")
    return productos
