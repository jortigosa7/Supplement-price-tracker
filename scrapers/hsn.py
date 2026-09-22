"""
scrapers/hsn.py — Scraper para HSN Store (hsnstore.com)

El grid de productos usa SSR (HTML estático del servidor). SpotlerSearch inyecta
el mismo grid vía XHR pero el HTML original ya contiene los form.product-item,
por lo que NO necesitamos Playwright para el listado.

Las páginas de detalle también se sirven en SSR: rating (JSON-LD), tabla nutricional
(div.nutritionalTable), servings (texto) y flavors (select anónimo) son extraíbles
con requests + BeautifulSoup.

Estrategia de caché:
  - Precio y peso: SIEMPRE petición fresca (no se cachean). Cada ejecución del
    scraper hace una petición por producto para obtener el precio actual.
  - Enriquecimiento (rating, nutrición, sabores): caché de 7 días.
    La petición fresca del paso anterior actualiza la caché, así que el
    enriquecimiento usa el HTML recién descargado sin petición adicional.
  → Peticiones por ejecución: ~7 (listados) + 1 por producto (detalle fresco)
"""

import json
import re
import time

import requests
from bs4 import BeautifulSoup

from .base import HEADERS, hacer_peticion, producto_base, seleccionar_mejor_formato
from .detail_cache import get_cached, save_cache

TIENDA   = "HSN"
BASE_URL = "https://www.hsnstore.com"
DELAY    = 2  # segundos entre peticiones

CATEGORIAS = [
    # Proteínas — todas van a la misma categoría "Proteinas Whey" para que el
    # matching cross-tienda funcione. El subtipo se guarda en protein_subtype.
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/whey",               "protein_subtype": "whey"},
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/caseina",             "protein_subtype": "caseína"},
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/vegetales",           "protein_subtype": "vegetal"},
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/albumina-de-huevo",   "protein_subtype": "huevo"},
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/liberacion-secuencial", "protein_subtype": "secuencial"},
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/carne",               "protein_subtype": "carne"},
    # Otras categorías
    {"nombre": "Creatina",       "url": f"{BASE_URL}/nutricion-deportiva/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/nutricion-deportiva/aminoacidos/bcaa-s-ramificados"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/nutricion-deportiva/pre-entrenamiento"},
]


# Productos a excluir aunque aparezcan en las URLs de categoría.
# Criterio: no son proteínas en polvo para batidos (errores de categorización HSN).
NOMBRES_EXCLUIR = {
    "crema de arroz proteica",  # aparece en caseína pero es un carbohidrato
}


def _excluido(nombre: str) -> bool:
    n = nombre.lower().strip()
    return any(excl in n for excl in NOMBRES_EXCLUIR)


# ── helpers ──────────────────────────────────────────────────────────────────

def _extraer_todas_opciones_select(soup: BeautifulSoup) -> list[tuple[float, str]]:
    """
    Extrae TODAS las opciones con peso del primer select de variantes HSN.
    Devuelve lista de (peso_kg, option_id) en el orden en que aparecen.
    """
    for sel in soup.find_all("select"):
        opciones = []
        for opt in sel.find_all("option"):
            texto = opt.get_text(strip=True)
            if not texto:
                continue
            m = re.search(r"(\d+[\.,]?\d*)\s*(kg|g)\b", texto, re.IGNORECASE)
            if m:
                val = float(m.group(1).replace(",", "."))
                unit = m.group(2).lower()
                if unit == "g":
                    val /= 1000
                peso_kg = round(val, 3)
                option_id = opt.get("value", "")
                opciones.append((peso_kg, option_id))
        if opciones:
            return opciones
    return []


def _extraer_peso_y_opcion_desde_select(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    """Primera opción con peso del select (alias de compatibilidad)."""
    opciones = _extraer_todas_opciones_select(soup)
    return opciones[0] if opciones else (None, None)


def _extraer_precio_opcion_detalle(html: str, option_id: str) -> float | None:
    """
    Extrae el finalPrice del JSON optionPrices de Magento 2 para una opción concreta.
    Patrón: "OPTION_ID":{"baseOldPrice":...,"finalPrice":{"amount":X}...}
    """
    if not option_id:
        return None
    idx = html.find(f'"{option_id}":')
    if idx == -1:
        return None
    snippet = html[idx: idx + 400]
    m = re.search(r'"finalPrice"\s*:\s*\{"amount"\s*:\s*([0-9.]+)', snippet)
    if m:
        return round(float(m.group(1)), 2)
    return None


# Mantener el nombre anterior como alias para no romper código que lo llame directamente
def _extraer_peso_kg_desde_select(soup: BeautifulSoup) -> float | None:
    peso, _ = _extraer_peso_y_opcion_desde_select(soup)
    return peso


def _extraer_sabores_desde_select(soup: BeautifulSoup, nombre_producto: str) -> list[str]:
    """
    Extrae los sabores del select de variantes de HSN.
    Cada opción tiene formato "NOMBRE_PRODUCTO Xkg SABOR".
    Elimina el prefijo de nombre+peso para obtener solo el sabor.
    """
    nombre_norm = re.sub(r"\s+", " ", nombre_producto.strip().lower())
    for sel in soup.find_all("select"):
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

    return enrichment


def _obtener_precio_peso_fresco(url: str) -> tuple[float | None, float | None]:
    """
    Hace SIEMPRE una petición fresca a la ficha de detalle de HSN.
    Devuelve (peso_kg, precio_eur) del formato con mejor €/kg disponible.

    Actualiza la caché con el HTML descargado para que _scrape_detalle() lo
    reutilice sin petición adicional.

    Si ningún formato tiene precio confirmado en optionPrices, devuelve
    (peso del primer formato, None) y el €/kg quedará como None.
    """
    r = hacer_peticion(url)
    if not r or r.status_code != 200:
        return None, None
    html = r.text
    save_cache("hsn", url, html)

    soup = BeautifulSoup(html, "html.parser")
    opciones = _extraer_todas_opciones_select(soup)
    if not opciones:
        return None, None

    # Buscar precio para cada opción y quedarse con la de mejor €/kg
    formatos_con_precio = []
    for peso_kg, option_id in opciones:
        precio = _extraer_precio_opcion_detalle(html, option_id)
        if precio:
            formatos_con_precio.append((peso_kg, precio))

    if not formatos_con_precio:
        # Sin precio confirmado para ningún formato: fallback al primer formato
        return opciones[0][0], None

    return seleccionar_mejor_formato(formatos_con_precio)


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
                if _excluido(nombre):
                    continue

                # Precio: HSN muestra precio especial en span.special-price .price
                precio_el = (
                    item.select_one("span.special-price .price")
                    or item.select_one('[data-price-type="finalPrice"] .price')
                    or item.select_one(".price-final_price .price")
                    or item.select_one("span.price")
                )
                precio = precio_el.get_text(strip=True) if precio_el else "N/A"

                # Imagen: primer <img> dentro del form (no usa clase fija)
                img = item.find("img")
                imagen_url = None
                if img:
                    src = img.get("data-src") or img.get("src") or ""
                    if src.startswith("http"):
                        imagen_url = src

                productos_raw.append({
                    "nombre":          nombre,
                    "precio":          precio,
                    "categoria":       cat["nombre"],
                    "url":             url_prod,
                    "imagen_url":      imagen_url,
                    "protein_subtype": cat.get("protein_subtype"),
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

    # ── Paso 2: páginas de detalle (precio fresco + enriquecimiento cacheado) ──
    # _obtener_precio_peso_fresco() hace SIEMPRE una petición a HSN y guarda
    # el HTML en caché. _scrape_detalle() lee inmediatamente esa caché fresca.
    # → 1 petición de red por producto (nunca 0, nunca 2).
    print(f"\n  Obteniendo precios frescos y enriqueciendo {len(productos_raw)} productos...")
    productos: list[dict] = []
    stats = {"ok": 0, "sin_precio_opcion": 0, "errors": 0}

    for i, d in enumerate(productos_raw):
        peso_kg, precio_confirmado = _obtener_precio_peso_fresco(d["url"])
        if peso_kg is None and precio_confirmado is None:
            stats["errors"] += 1
        elif precio_confirmado is None:
            stats["sin_precio_opcion"] += 1
        else:
            stats["ok"] += 1

        # Enriquecimiento desde la caché recién actualizada (sin petición extra)
        enrichment = _scrape_detalle(d["url"], d["nombre"])

        # Nombre: reflejar siempre el formato del que sale el precio
        nombre_final = d["nombre"]
        if peso_kg:
            m_peso = re.search(r"(\d+[\.,]?\d*)\s*(kg|g)\b", nombre_final, re.I)
            if not m_peso:
                nombre_final = f"{nombre_final} {_talla_str(peso_kg)}"
            else:
                val = float(m_peso.group(1).replace(",", "."))
                unit = m_peso.group(2).lower()
                peso_en_nombre = val / 1000 if unit == "g" else val
                if abs(peso_en_nombre - peso_kg) > 0.001:
                    # El nombre lleva el peso de otro formato: reemplazar con el seleccionado
                    nombre_final = re.sub(
                        r"\s*\d+[\.,]?\d*\s*(?:kg|g)\b",
                        f" {_talla_str(peso_kg)}",
                        nombre_final,
                        count=1,
                        flags=re.IGNORECASE,
                    ).strip()

        # Precio: usar el de la opción concreta (confirmado) o el de lista como fallback
        precio_final = str(precio_confirmado) if precio_confirmado else d["precio"]

        prod = producto_base(
            nombre_final,
            precio_final,
            "",           # marca: matching.py la extrae
            d["categoria"],
            TIENDA,
            d["url"],
            d.get("imagen_url"),
        )
        prod.update(enrichment)

        # Subtipo de proteína (solo para categorías de proteínas de HSN)
        if d.get("protein_subtype"):
            prod["protein_subtype"] = d["protein_subtype"]

        # Si el peso se conoce pero el precio no está confirmado para ese formato,
        # marcar para que matching.py no calcule €/kg con precio/peso inconsistentes.
        if peso_kg and not precio_confirmado:
            prod["_precio_sin_confirmar"] = True

        productos.append(prod)

        if (i + 1) % 10 == 0:
            print(f"  ... {i+1}/{len(productos_raw)} "
                  f"(ok:{stats['ok']} / sin_precio_opcion:{stats['sin_precio_opcion']} / err:{stats['errors']})")
        time.sleep(1)

    print(f"\n  Total HSN: {len(productos)} productos")
    print(f"  Detalle: {stats['ok']} precio confirmado, "
          f"{stats['sin_precio_opcion']} sin precio de opción (€/kg=None), "
          f"{stats['errors']} errores")
    return productos
