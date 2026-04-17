"""
scrapers/nutritienda.py — Scraper para Nutritienda.com
Usa requests + BeautifulSoup (HTML server-side renderizado).

Las páginas de detalle se cachean 7 días. La extracción de campos
de enriquecimiento usa div.nutritional-snippet (texto delimitado por |).
El rating viene del JSON-LD @type=Product con ratingValue en escala 0-10.
"""

import json
import re
import time

from bs4 import BeautifulSoup

from .base import hacer_peticion, producto_base
from .detail_cache import get_cached, save_cache

TIENDA = "Nutritienda"
DELAY  = 3

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": "https://www.nutritienda.com/es/proteinas-suero-whey"},
    {"nombre": "Creatina",       "url": "https://www.nutritienda.com/es/creatina"},
    {"nombre": "BCAA",           "url": "https://www.nutritienda.com/es/bcaas"},
    {"nombre": "Pre-Entreno",    "url": "https://www.nutritienda.com/es/pre-entrenamiento"},
]


def _scrape_detalle(url: str) -> dict:
    """
    Visita la página de detalle de un producto Nutritienda (caché 7 días) y extrae:
    - store_rating, store_rating_count, store_rating_url  (JSON-LD Product)
      NOTA: Nutritienda usa escala 0-10 → se divide entre 2 para normalizar a 0-5.
    - serving_size_g          (div.nutritional-snippet, campo "Dosis")
    - servings_per_container  (campo "Dosis por envase")
    - protein_per_serving_g   (fila "Proteínas", columna "Dosis")
    - flavors_available       (opciones al inicio del snippet, antes de "Complemento")
    - sweetener_free          (búsqueda de texto en nombre del producto en snippet)
    """
    html = get_cached("nutritienda", url)
    if html is None:
        r = hacer_peticion(url)
        if not r or r.status_code != 200:
            return {}
        html = r.text
        save_cache("nutritienda", url, html)

    soup = BeautifulSoup(html, "lxml")
    enrichment: dict = {}

    # ── Rating desde JSON-LD ────────────────────────────────────────────────
    # Nutritienda usa escala 0-10, NO 0-5 como el resto de tiendas.
    # Se divide entre 2 para homogeneizar la escala antes de guardar.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if data.get("@type") == "Product":
                agg = data.get("aggregateRating", {})
                rv = agg.get("ratingValue")
                rc = agg.get("reviewCount")
                if rv:
                    # ÷ 2: Nutritienda puntúa sobre 10, normalizamos a escala 0-5
                    enrichment["store_rating"] = round(float(rv) / 2, 2)
                if rc:
                    enrichment["store_rating_count"] = int(rc)
                    enrichment["store_rating_url"] = url
                break
        except Exception:
            pass

    # ── Datos nutricionales desde div.nutritional-snippet ───────────────────
    # El snippet es texto delimitado por | con este formato:
    # NOMBRE|SABOR_1|SABOR_2|...|Complemento Alimenticio|Información Nutricional|
    # Dosis|X g|Dosis por envase|Y|Dosis diaria|Z g|Cantidad por|Dosis|Día|100 g|
    # Valor Energético|...|Proteínas|P g|P g|P100g|...
    div = soup.find("div", class_="nutritional-snippet")
    if div:
        parts = [p.strip() for p in div.get_text(separator="|").split("|") if p.strip()]

        # ── Flavors: elementos antes de "Complemento Alimenticio" ──────────
        # El primer elemento es el nombre del producto; los siguientes son sabores
        try:
            comp_idx = next(i for i, p in enumerate(parts) if "complemento" in p.lower())
            # Sabores: partes 1..comp_idx-1 (saltando el nombre del producto en idx 0)
            sabores = parts[1:comp_idx]
            # Descartar si son headers nutricionales o muy cortos
            sabores = [s for s in sabores if len(s) > 2 and "informaci" not in s.lower()]
            # Deduplicar manteniendo orden
            seen: set = set()
            sabores_uniq = []
            for s in sabores:
                if s not in seen:
                    seen.add(s)
                    sabores_uniq.append(s)
            if sabores_uniq:
                enrichment["flavors_available"] = sabores_uniq
        except StopIteration:
            pass

        # ── Serving size ────────────────────────────────────────────────────
        try:
            dosis_idx = next(i for i, p in enumerate(parts) if p.lower() == "dosis")
            dosis_val = parts[dosis_idx + 1] if dosis_idx + 1 < len(parts) else ""
            m = re.search(r"([\d,\.]+)\s*g\b", dosis_val)
            if m:
                enrichment["serving_size_g"] = float(m.group(1).replace(",", "."))
        except StopIteration:
            pass

        # ── Servings per container ──────────────────────────────────────────
        try:
            dpe_idx = next(
                i for i, p in enumerate(parts) if "dosis por envase" in p.lower()
            )
            dpe_val = parts[dpe_idx + 1] if dpe_idx + 1 < len(parts) else ""
            m = re.search(r"(\d+)", dpe_val)
            if m:
                enrichment["servings_per_container"] = int(m.group(1))
        except StopIteration:
            pass

        # ── Protein per serving ─────────────────────────────────────────────
        # Buscar "Proteínas" en la lista y tomar el valor siguiente (columna Dosis)
        for i, part in enumerate(parts):
            if re.match(r"prote[íi]nas?$", part, re.IGNORECASE):
                val = parts[i + 1] if i + 1 < len(parts) else ""
                m = re.search(r"([\d,\.]+)\s*g\b", val)
                if m:
                    enrichment["protein_per_serving_g"] = float(
                        m.group(1).replace(",", ".")
                    )
                break

    return enrichment


def scrape() -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    productos_raw: list[dict] = []

    for cat in CATEGORIAS:
        print(f"\n  Categoria: {cat['nombre']}")
        response = hacer_peticion(cat["url"])
        if not response:
            print(f"  Sin respuesta, saltando...")
            continue

        soup = BeautifulSoup(response.text, "lxml")
        items = soup.select("div.grid-info-wrapper")

        if not items:
            items_price = soup.find_all("span", class_="price")
            items = [p.parent.parent for p in items_price if p.parent]

        print(f"  Encontrados: {len(items)} productos")

        for item in items:
            try:
                precio_elem = item.select_one("span.price")
                nombre_elem = item.select_one("h3 a")
                if not nombre_elem:
                    continue

                nombre = nombre_elem.get_text(strip=True)
                precio = precio_elem.get_text(strip=True) if precio_elem else "N/A"

                marca = ""
                title = nombre_elem.get("title", "")
                if " - " in title:
                    marca = title.split(" - ")[-1].strip()

                href = nombre_elem.get("href", "")
                url = href if href.startswith("http") else "https://www.nutritienda.com" + href

                imagen_url = None
                contenedor = item.parent or item
                img = contenedor.select_one("img[src]")
                if img:
                    src = img.get("data-src") or img.get("src", "")
                    if src and "placeholder" not in src.lower() and src.startswith("http"):
                        imagen_url = src

                if nombre:
                    productos_raw.append({
                        "nombre":     nombre,
                        "precio":     precio,
                        "marca":      marca,
                        "categoria":  cat["nombre"],
                        "url":        url,
                        "imagen_url": imagen_url,
                    })
            except Exception as e:
                print(f"  Error en producto: {e}")

        print(f"  Acumulado: {len(productos_raw)}")
        time.sleep(DELAY)

    # ── Detalle: enriquecimiento ───────────────────────────────────────────
    print(f"\n  Enriqueciendo {len(productos_raw)} productos (detalle + caché 7 días)...")
    productos: list[dict] = []
    stats = {"cached": 0, "fetched": 0, "errors": 0}

    for i, d in enumerate(productos_raw):
        cached_check = get_cached("nutritienda", d["url"])
        if cached_check is not None:
            stats["cached"] += 1
        else:
            stats["fetched"] += 1

        enrichment = _scrape_detalle(d["url"])
        if not enrichment and cached_check is None:
            stats["errors"] += 1

        prod = producto_base(
            d["nombre"],
            d["precio"],
            d["marca"],
            d["categoria"],
            TIENDA,
            d["url"],
            d.get("imagen_url"),
        )
        prod.update(enrichment)
        productos.append(prod)

        if (i + 1) % 10 == 0:
            print(
                f"  ... {i+1}/{len(productos_raw)} "
                f"(caché:{stats['cached']} / fetch:{stats['fetched']} / err:{stats['errors']})"
            )
        time.sleep(1)

    print(f"\n  Total Nutritienda: {len(productos)} productos")
    print(
        f"  Detalle: {stats['fetched']} fetcheados, "
        f"{stats['cached']} desde caché, {stats['errors']} errores"
    )
    return productos
