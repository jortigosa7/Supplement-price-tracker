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

import json
import math
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
MAX_POR_CATEGORIA = 40


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
    return items_all[:MAX_POR_CATEGORIA]


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

    print(f"\n  Total Nutritienda: {len(productos)} productos")
    print(
        f"  Detalle: {stats['fetched']} fetcheados, "
        f"{stats['cached']} desde caché, {stats['errors']} errores"
    )
    return productos
