"""
scrapers/nutritienda.py — Scraper para Nutritienda.com
Usa requests + BeautifulSoup sobre JSON-LD (sitio Nuxt desde sep 2026).

La página de listado de cada categoría expone un ItemList en JSON-LD con
nombre, URL, imagen, precio y marca de los productos. Todos los productos
se obtienen en una sola petición usando el parámetro ?page=N (acumulativo).

Las páginas de detalle se cachean 7 días. Se visitan para obtener el nombre
completo con peso (field `name` del JSON-LD Product, ej "Evowhey 2 Kg - HSN")
y el rating (escala 0-5 directamente, sin división).

El nutritional-snippet del HTML anterior desapareció en la migración Nuxt;
los campos de enrichment nutricional (serving_size_g, etc.) ya no se extraen.
"""

import datetime
import json
import math
import os
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

# Máximo de productos por categoría para no sobrecargar el catálogo
MAX_POR_CATEGORIA = 80

# Productos fijos que siempre se incluyen aunque estén más allá del cap de listado.
# Formato: (url, categoria)  — se añaden al batch del listado si aún no están presentes.
URLS_FIJAS = [
    # Creatinas más allá del cap que tienen comparaciones con clics en GSC
    ("https://www.nutritienda.com/es/amazin-foods/creatina-creapure-400g",          "Creatina"),
    ("https://www.nutritienda.com/es/keepgoing/creatina-celular-800g",              "Creatina"),
    ("https://www.nutritienda.com/es/vitobest/creatine-monohydrate-creapure-200g",  "Creatina"),
    # Proteínas más allá del cap
    ("https://www.nutritienda.com/es/optimum-nutrition/100-whey-gold-standard",     "Proteinas Whey"),
    ("https://www.nutritienda.com/es/amix-nutrition/predator-protein",              "Proteinas Whey"),
    ("https://www.nutritienda.com/es/biotech-usa/iso-whey-zero-black",              "Proteinas Whey"),
]

CATALOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nutritienda_catalog.json")


def _cargar_catalogo() -> dict:
    """Carga el catálogo persistente de Nutritienda. Devuelve {} si no existe."""
    try:
        with open(CATALOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_catalogo(catalogo: dict) -> None:
    """Guarda el catálogo persistente."""
    os.makedirs(os.path.dirname(CATALOG_FILE), exist_ok=True)
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)


def _parse_itemlist(html: str) -> tuple[int, list[dict]]:
    """
    Extrae el ItemList del JSON-LD de una página de listado.
    Devuelve (total_declarado, lista_de_items).
    Cada item: {nombre, url, imagen_url, precio, marca}
    """
    soup = BeautifulSoup(html, "lxml")
    ld = soup.find("script", type="application/ld+json")
    if not ld:
        return 0, []
    try:
        data = json.loads(ld.string or "")
    except Exception:
        return 0, []

    graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
    for node in graph:
        if node.get("@type") != "ItemList":
            continue
        total = node.get("numberOfItems", 0)
        items = []
        for entry in node.get("itemListElement", []):
            item = entry.get("item", {})
            nombre = item.get("name", "")
            url = item.get("url", "")
            imagen_raw = item.get("image", "")
            imagen_url = imagen_raw if isinstance(imagen_raw, str) else (imagen_raw[0] if imagen_raw else None)
            marca = item.get("brand", {}).get("name", "")
            offers = item.get("offers", {})
            precio = str(offers.get("price") or offers.get("lowPrice") or "")
            if nombre and url and precio:
                items.append({
                    "nombre":     nombre,
                    "precio":     precio,
                    "marca":      marca,
                    "url":        url,
                    "imagen_url": imagen_url,
                })
        return total, items
    return 0, []


def _scrape_listado(url_cat: str) -> list[dict]:
    """
    Scrape todos los productos de una categoría.
    Hace una primera petición para conocer el total, luego pide la última
    página (que devuelve todos los items de forma acumulativa) y recorta
    al límite MAX_POR_CATEGORIA.
    """
    r = hacer_peticion(url_cat)
    if not r:
        return []

    total, items_p1 = _parse_itemlist(r.text)
    if not total:
        return items_p1[:MAX_POR_CATEGORIA]

    items_por_pagina = len(items_p1) if items_p1 else 20
    if total <= items_por_pagina or total <= MAX_POR_CATEGORIA:
        return items_p1[:MAX_POR_CATEGORIA]

    # Calcular última página necesaria para cubrir MAX_POR_CATEGORIA
    paginas_necesarias = math.ceil(min(total, MAX_POR_CATEGORIA) / items_por_pagina)
    if paginas_necesarias <= 1:
        return items_p1[:MAX_POR_CATEGORIA]

    time.sleep(DELAY)
    r2 = hacer_peticion(f"{url_cat}?page={paginas_necesarias}")
    if not r2:
        return items_p1[:MAX_POR_CATEGORIA]

    _, items_all = _parse_itemlist(r2.text)

    # Validar que la respuesta es completa; reintentar si viene truncada
    esperado = min(total, MAX_POR_CATEGORIA)
    if len(items_all) < esperado * 0.7:
        print(
            f"  [aviso] Respuesta incompleta ({len(items_all)}/{esperado} productos). "
            f"Reintentando en 5s..."
        )
        time.sleep(5)
        r3 = hacer_peticion(f"{url_cat}?page={paginas_necesarias}")
        if r3:
            _, items_all = _parse_itemlist(r3.text)
            print(f"  Reintento: {len(items_all)} productos")

    resultado = items_all[:MAX_POR_CATEGORIA]
    # Aviso si seguimos tocando el techo — puede haber más productos sin scraper
    if len(resultado) >= MAX_POR_CATEGORIA and total > MAX_POR_CATEGORIA:
        print(f"  ⚠️  AVISO: categoría alcanza el techo ({MAX_POR_CATEGORIA}/{total} productos). "
              f"Sube MAX_POR_CATEGORIA para no perder productos.")
    return resultado


def _scrape_detalle(url: str) -> tuple[str, dict]:
    """
    Visita la página de detalle (caché 7 días) y extrae desde JSON-LD Product:
    - _nombre_completo: nombre con peso incluido (ej "Evowhey protein 2 Kg")
    - store_rating, store_rating_count, store_rating_url

    Nota: el nutritional-snippet del HTML anterior no existe en el nuevo sitio.
    El rating ya está en escala 0-5 (sin división).

    Devuelve (final_url, enrichment).
    """
    final_url = url
    html = get_cached("nutritienda", url)
    if html is None:
        r = hacer_peticion(url)
        if not r or r.status_code != 200:
            return url, {}
        final_url = r.url  # URL final tras redirecciones 301
        html = r.text
        save_cache("nutritienda", url, html)

    soup = BeautifulSoup(html, "lxml")
    enrichment: dict = {}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for node in graph:
                if node.get("@type") != "Product":
                    continue

                # Nombre completo con peso, stripeando " - Marca" al final.
                # La capitalización en JSON-LD puede diferir del listing,
                # por eso se busca case-insensitive desde el final.
                nombre_raw = node.get("name", "")
                marca_raw = node.get("brand", {}).get("name", "")
                nombre_completo = nombre_raw
                if marca_raw:
                    patron = re.compile(
                        r"\s*-\s*" + re.escape(marca_raw) + r".*$",
                        re.IGNORECASE,
                    )
                    nombre_completo = patron.sub("", nombre_raw).strip()
                if nombre_completo:
                    enrichment["_nombre_completo"] = nombre_completo

                # Tamaño del producto (fallback si el nombre no tiene peso)
                size = node.get("size", "")
                if size:
                    enrichment["_size"] = size

                # Rating (escala 0-5 directamente en el nuevo sitio)
                agg = node.get("aggregateRating", {})
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

    return final_url, enrichment


def _scrape_producto_fijo(url: str, categoria: str) -> dict | None:
    """
    Extrae un producto completo (nombre, precio, marca, imagen) desde la página
    de detalle vía JSON-LD Product. Se usa para URLS_FIJAS que pueden estar fuera
    del cap de listado.

    Devuelve un dict compatible con el formato de _scrape_listado() o None si falla.
    """
    html = get_cached("nutritienda", url)
    final_url = url
    if html is None:
        r = hacer_peticion(url)
        if not r or r.status_code != 200:
            return None
        final_url = r.url
        html = r.text
        save_cache("nutritienda", url, html)

    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for node in graph:
                if node.get("@type") != "Product":
                    continue
                nombre_raw = node.get("name", "")
                marca_raw = node.get("brand", {}).get("name", "")
                nombre_completo = nombre_raw
                if marca_raw:
                    patron = re.compile(r"\s*-\s*" + re.escape(marca_raw) + r".*$", re.IGNORECASE)
                    nombre_completo = patron.sub("", nombre_raw).strip()
                offers = node.get("offers", {})
                precio = str(offers.get("price") or offers.get("lowPrice") or "")
                imagen_raw = node.get("image", "")
                imagen_url = imagen_raw if isinstance(imagen_raw, str) else (imagen_raw[0] if imagen_raw else None)
                if nombre_completo and precio:
                    return {
                        "nombre":     nombre_completo,
                        "precio":     precio,
                        "marca":      marca_raw,
                        "categoria":  categoria,
                        "url":        final_url,
                        "imagen_url": imagen_url,
                    }
        except Exception:
            pass
    return None


def scrape() -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    productos_raw: list[dict] = []

    for cat in CATEGORIAS:
        print(f"\n  Categoria: {cat['nombre']}")
        items = _scrape_listado(cat["url"])
        for item in items:
            item["categoria"] = cat["nombre"]
        productos_raw.extend(items)
        print(f"  Encontrados: {len(items)} productos")
        print(f"  Acumulado: {len(productos_raw)}")
        time.sleep(DELAY)

    # ── URLs fijas: productos específicos que deben incluirse siempre ─────────
    if URLS_FIJAS:
        urls_ya_presentes = {p["url"] for p in productos_raw}
        print(f"\n  Añadiendo URLs fijas ({len(URLS_FIJAS)} configuradas)...")
        for url_fija, cat_fija in URLS_FIJAS:
            if url_fija in urls_ya_presentes:
                print(f"  ↩️  Ya en listado: {url_fija.split('/es/')[-1]}")
                continue
            time.sleep(DELAY)
            item_fijo = _scrape_producto_fijo(url_fija, cat_fija)
            if item_fijo:
                productos_raw.append(item_fijo)
                urls_ya_presentes.add(item_fijo["url"])  # usar URL final (tras 301)
                print(f"  ✅ Fijo añadido: {item_fijo['nombre'][:60]}")
            else:
                print(f"  ⚠️  No se pudo obtener URL fija: {url_fija}")

    # ── Catálogo persistente: incluir productos conocidos aunque caigan del top-80 ──
    catalogo = _cargar_catalogo()
    hoy = datetime.date.today().isoformat()

    # Registrar todas las URLs del listado de hoy en el catálogo
    urls_en_listado = {p["url"] for p in productos_raw}
    for p in productos_raw:
        if p["url"] not in catalogo:
            catalogo[p["url"]] = {"categoria": p["categoria"], "first_seen": hoy}

    # Para URLs del catálogo que no aparecen en el listado de hoy: verificar que siguen vivas
    urls_a_retirar = []
    catalog_recuperados = 0
    for url_cat, meta in catalogo.items():
        if url_cat in urls_en_listado:
            continue  # ya está en el listado, no hace falta nada
        # Intentar obtener el producto desde la caché o desde la tienda
        item_fijo = _scrape_producto_fijo(url_cat, meta["categoria"])
        if item_fijo:
            productos_raw.append(item_fijo)
            catalog_recuperados += 1
        else:
            urls_a_retirar.append(url_cat)

    if catalog_recuperados:
        print(f"  Catálogo: {catalog_recuperados} productos recuperados (no en top-{MAX_POR_CATEGORIA} hoy)")
    if urls_a_retirar:
        for url in urls_a_retirar:
            del catalogo[url]
        print(f"  Catálogo: {len(urls_a_retirar)} URL(s) retiradas (404 o error persistente)")

    _guardar_catalogo(catalogo)

    # ── Detalle: nombre completo con peso + rating ─────────────────────────
    print(f"\n  Enriqueciendo {len(productos_raw)} productos (detalle + caché 7 días)...")
    productos: list[dict] = []
    stats = {"cached": 0, "fetched": 0, "errors": 0}

    for i, d in enumerate(productos_raw):
        cached_check = get_cached("nutritienda", d["url"])
        if cached_check is not None:
            stats["cached"] += 1
        else:
            stats["fetched"] += 1

        final_url, enrichment = _scrape_detalle(d["url"])
        if not enrichment and cached_check is None:
            stats["errors"] += 1

        # Usar nombre completo del detalle; si no tiene peso, añadir el campo size
        nombre = enrichment.pop("_nombre_completo", d["nombre"])
        size_raw = enrichment.pop("_size", "")
        if size_raw and not re.search(r"\d+\s*(kg|g)\b", nombre, re.IGNORECASE):
            # Normalizar "2270 g" → "2270g", "2 Kg" → "2kg"
            size_norm = re.sub(r"\s+", "", size_raw).lower()
            nombre = f"{nombre} {size_norm}"

        prod = producto_base(
            nombre,
            d["precio"],
            d["marca"],
            d["categoria"],
            TIENDA,
            final_url,
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

    total = len(productos)
    print(f"\n  Total Nutritienda: {total} productos")
    print(
        f"  Detalle: {stats['fetched']} fetcheados, "
        f"{stats['cached']} desde caché, {stats['errors']} errores"
    )

    # Guardia: falla duro si el scrape devuelve 0 productos (scraper roto)
    if total == 0:
        raise RuntimeError(
            "Nutritienda scraper devolvió 0 productos — "
            "posible cambio de frontend. Revisa _parse_itemlist."
        )

    # Aviso si el total es sospechosamente bajo respecto al mínimo histórico
    MINIMO_ESPERADO = 120  # menos de esto indica scraper parcialmente roto
    if total < MINIMO_ESPERADO:
        print(
            f"  ⚠️  AVISO: solo {total} productos (mínimo esperado: {MINIMO_ESPERADO}). "
            "Revisar si alguna categoría devolvió 0."
        )

    return productos
