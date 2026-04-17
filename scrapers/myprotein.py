"""
scrapers/myprotein.py — Scraper para MyProtein España (myprotein.es)

Los datos de producto están en JSON-LD (<script type="application/ld+json">)
tanto en las páginas de categoría (ItemList) como en las de producto (Product).

Proceso en dos fases (igual que HSN):
  Fase 1 — Páginas de categoría: extrae nombre y URL de cada producto.
  Fase 2 — Página de producto:   extrae variantes de peso y precio.
           Se queda con el peso mínimo disponible.

SETUP: no requiere dependencias adicionales (usa requests + BS4).
DEBUG: python scraper.py --debug-myprotein
"""

import json
import re
import time
from bs4 import BeautifulSoup
from .base import hacer_peticion, producto_base
from .detail_cache import get_cached, save_cache

TIENDA   = "MyProtein"
BASE_URL = "https://www.myprotein.es"
DELAY    = 2
MAX_PAGES = 8  # límite de seguridad por categoría

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/c/nutrition/protein/"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/c/nutrition/creatine/"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/c/nutrition/amino-acids/bcaa/"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/c/performance/aminos-preworkout/"},
]


# ── Utilidades ───────────────────────────────────────────────────────────────

def _parsear_schemas_jsonld(html: str) -> list[dict]:
    """
    Devuelve todos los objetos JSON-LD del HTML como lista.
    Maneja las tres formas comunes:
      - Objeto plano: { "@type": "ItemList", ... }
      - Array:        [ { "@type": "..." }, ... ]
      - @graph:       { "@graph": [ { "@type": "ItemList", ... }, ... ] }
    """
    # Forzar UTF-8 si html llega como bytes
    if isinstance(html, (bytes, bytearray)):
        html = html.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "lxml")
    schemas = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(data, list):
            schemas.extend(data)
        elif isinstance(data, dict):
            if "@graph" in data:
                schemas.extend(data["@graph"])  # MyProtein usa @graph
            else:
                schemas.append(data)
    return schemas


def _peso_kg_de_texto(texto: str) -> float | None:
    """Extrae peso en kg de un texto ('500g', '2.5kg', '1 kg')."""
    texto = texto.lower()
    m = re.search(r"(\d+[.,]?\d*)\s*kg", texto)
    if m:
        return round(float(m.group(1).replace(",", ".")), 3)
    m = re.search(r"(\d+)\s*g(?:r)?(?:\b|$)", texto)
    if m:
        return round(int(m.group(1)) / 1000, 3)
    return None


def _talla_str(peso_kg: float) -> str:
    """0.5 → '500g',  1.0 → '1kg',  2.5 → '2.5kg'"""
    if peso_kg < 1:
        return f"{round(peso_kg * 1000)}g"
    return f"{peso_kg:g}kg"


# ── Fase 1: listado de categoría ─────────────────────────────────────────────

def _extraer_listado(html: str) -> list[dict]:
    """
    Extrae productos del JSON-LD @type ItemList de la página de categoría.
    Cada ítem devuelve {nombre, precio_listing, url}.
    """
    productos = []
    for schema in _parsear_schemas_jsonld(html):
        if schema.get("@type") != "ItemList":
            continue
        for wrapper in schema.get("itemListElement", []):
            item = wrapper.get("item", wrapper)
            nombre = item.get("name", "").strip()
            if not nombre:
                continue

            # Precio de listing (fallback si la página de producto falla)
            precio_eur = None
            offers = item.get("offers", {})
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                try:
                    precio_eur = float(offers.get("price", 0)) or None
                except (TypeError, ValueError):
                    precio_eur = None

            url = item.get("url", "")
            if url and not url.startswith("http"):
                url = BASE_URL + url

            if url:
                productos.append({
                    "nombre":         nombre,
                    "precio_listing": str(precio_eur) if precio_eur else "N/A",
                    "url":            url,
                })
    return productos


# ── Fase 2: página de producto (pesos + precios + enriquecimiento) ───────────

def _extraer_enriquecimiento(html: str) -> dict:
    """
    Extrae campos de enriquecimiento del JSON-LD @graph de la página de producto.
    No extrae nutricionales (protein_per_serving_g, etc.) porque MyProtein los carga
    vía JS — solo rating y flavors son extraíbles desde el HTML estático.

    - store_rating:       ProductGroup.aggregateRating.ratingValue (escala 0-5)
    - store_rating_count: aggregateRating.reviewCount
    - flavors_available:  hasVariant[].additionalProperty[name="flavour"] → únicos
    """
    enrichment: dict = {}
    for schema in _parsear_schemas_jsonld(html):
        if schema.get("@type") != "ProductGroup":
            continue

        agg = schema.get("aggregateRating", {})
        rv = agg.get("ratingValue")
        rc = agg.get("reviewCount")
        if rv:
            enrichment["store_rating"] = round(float(rv), 2)
        if rc:
            enrichment["store_rating_count"] = int(rc)

        # Flavors desde hasVariant[].additionalProperty
        sabores: list[str] = []
        seen: set = set()
        for variant in schema.get("hasVariant", []):
            for prop in variant.get("additionalProperty", []):
                if prop.get("name", "").lower() == "flavour":
                    sabor = str(prop.get("value", "")).strip()
                    if sabor and sabor not in seen:
                        seen.add(sabor)
                        sabores.append(sabor)
        if sabores:
            enrichment["flavors_available"] = sabores
        break  # solo el primer ProductGroup

    return enrichment


def _extraer_variantes(html: str) -> tuple[list[tuple[float, float]], str | None]:
    """
    Extrae variantes (peso_kg, precio_eur) del JSON-LD @type Product.
    Devuelve (lista ordenada por peso ascendente, imagen_url o None).
    """
    variantes = []
    imagen_url = None

    for schema in _parsear_schemas_jsonld(html):
        if schema.get("@type") not in ("Product", "IndividualProduct"):
            continue

        # Imagen del producto
        if not imagen_url:
            img = schema.get("image")
            if isinstance(img, str) and img.startswith("http"):
                imagen_url = img
            elif isinstance(img, list) and img:
                imagen_url = img[0] if isinstance(img[0], str) else None

        offers = schema.get("offers", [])
        if isinstance(offers, dict):
            offers = [offers]

        for offer in offers:
            offer_name = offer.get("name", schema.get("name", ""))
            peso = _peso_kg_de_texto(offer_name)
            if not peso:
                continue
            try:
                precio = float(str(offer.get("price", "0")).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if precio > 0:
                variantes.append((peso, precio))

    by_peso: dict[float, float] = {}
    for peso, precio in variantes:
        key = round(peso, 2)
        if key not in by_peso or precio < by_peso[key]:
            by_peso[key] = precio

    return sorted(by_peso.items()), imagen_url


# ── Scraper principal ─────────────────────────────────────────────────────────

def scrape(debug: bool = False) -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    productos_raw = []  # sin peso todavía

    # ── Fase 1: listados de categoría ─────────────────────────────────────
    for cat in CATEGORIAS:
        print(f"\n  Categoria: {cat['nombre']}")
        urls_vistas: set[str] = set()
        pagina = 1

        while pagina <= MAX_PAGES:
            url = cat["url"] if pagina == 1 else f"{cat['url']}?pageNumber={pagina}"
            print(f"  Página {pagina}: {url}")

            response = hacer_peticion(url)
            if not response:
                print(f"  Sin respuesta.")
                break

            # Forzar UTF-8: requests a veces auto-detecta Latin-1 en páginas es-ES
            html = response.content.decode("utf-8", errors="replace")

            if debug:
                slug = cat["nombre"].lower().replace(" ", "_")
                fname = f"debug_myprotein_{slug}_p{pagina}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  [DEBUG] HTML guardado → {fname}")
                break

            items = _extraer_listado(html)
            if not items:
                print(f"  Sin productos en JSON-LD (fin de paginación).")
                break

            nuevos = 0
            for item in items:
                if item["url"] in urls_vistas:
                    continue
                urls_vistas.add(item["url"])
                productos_raw.append({**item, "categoria": cat["nombre"]})
                nuevos += 1

            print(f"  +{nuevos} nuevos (acumulado: {len(productos_raw)})")

            if nuevos == 0:
                break

            pagina += 1
            time.sleep(DELAY)

        time.sleep(DELAY)

    if debug:
        return []

    # ── Fase 2: visitar cada producto (peso, precio, rating, flavors) ────────
    print(f"\n  Obteniendo tallas y enriquecimiento ({len(productos_raw)} productos)...")
    productos = []
    stats = {"cached": 0, "fetched": 0, "errors": 0}

    for i, d in enumerate(productos_raw):
        nombre_final = d["nombre"]
        precio_final = d["precio_listing"]
        imagen_url = None
        enrichment: dict = {}

        try:
            html_prod = get_cached("myprotein", d["url"])
            if html_prod is not None:
                stats["cached"] += 1
            else:
                resp = hacer_peticion(d["url"])
                if resp:
                    html_prod = resp.content.decode("utf-8", errors="replace")
                    save_cache("myprotein", d["url"], html_prod)
                    stats["fetched"] += 1
                else:
                    stats["errors"] += 1

            if html_prod:
                variantes, imagen_url = _extraer_variantes(html_prod)
                if variantes:
                    peso_min, precio_min = variantes[0]
                    nombre_final = f"{d['nombre']} {_talla_str(peso_min)}"
                    precio_final = str(precio_min)
                enrichment = _extraer_enriquecimiento(html_prod)
                if enrichment.get("store_rating_count"):
                    enrichment["store_rating_url"] = d["url"]
        except Exception:
            stats["errors"] += 1

        prod = producto_base(
            nombre_final, precio_final, "", d["categoria"], TIENDA, d["url"], imagen_url
        )
        prod.update(enrichment)
        productos.append(prod)

        if (i + 1) % 10 == 0:
            print(
                f"  ... {i+1}/{len(productos_raw)} "
                f"(caché:{stats['cached']} / fetch:{stats['fetched']} / err:{stats['errors']})"
            )
        time.sleep(1)

    print(f"\n  Total {TIENDA}: {len(productos)} productos")
    print(
        f"  Detalle: {stats['fetched']} fetcheados, "
        f"{stats['cached']} desde caché, {stats['errors']} errores"
    )
    return productos
