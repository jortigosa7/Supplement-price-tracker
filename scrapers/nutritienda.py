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


def _extraer_peso_g(texto: str) -> float | None:
    """Extrae el peso en gramos de una cadena de texto.
    '2270 g' → 2270.0, '2 Kg' → 2000.0, '1816g' → 1816.0.
    """
    m = re.search(r"(\d+[\.,]?\d*)\s*(kg|g)\b", texto, re.IGNORECASE)
    if not m:
        return None
    valor = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return valor * 1000 if unit == "kg" else valor


def _extraer_unidades(texto: str):
    """Extrae (count, unit_norm) de texto como '120 VCaps', '90 Caps', '12 Ud'.
    Devuelve None si no hay coincidencia.
    """
    PATRONES = [
        (r"vcaps?|v\.?caps?",               "vcap"),
        (r"caps?|c[aá]psulas?|caplets?",    "cap"),
        (r"softgels?",                       "softgel"),
        (r"tabs?|tabletas?|comprimidos?",    "tab"),
        (r"sobres?|sticks?|sachets?",        "sobre"),
        (r"uds?|unidades?|unidad",           "ud"),
    ]
    for patron, norm in PATRONES:
        m = re.search(rf"(\d+)\s*(?:{patron})\b", texto, re.IGNORECASE)
        if m:
            return (int(m.group(1)), norm)
    return None


def _resolver_precio_variante(
    offers: dict,
    sku_root,
    size_page_g: float | None,
    peso_nombre_g: float | None,
    unidades_nombre=None,
) -> tuple[float | None, bool, bool]:
    """Devuelve (precio, sin_confirmar, agotado).

    agotado=True cuando todos los variants están OutOfStock (precio = último conocido).
    sin_confirmar=True cuando no se puede identificar la variante con seguridad.

    Estrategias (en orden):
    1. Offer simple.
    2. AggregateOffer sin desglose → uses offers["price"].
    3. AggregateOffer con offers individuales:
       OOS: si ninguno InStock → devuelve min precio con agotado=True.
       a. Coincidencia por peso o unidades en offer.name → min precio de matches InStock.
       b. size_page ≈ peso_nombre → collect InStock offers que no contradigan el tamaño → min precio.
    4. Si nada funciona → (None, True, False).
    """
    TOLERANCIA = 0.02

    otype = offers.get("@type", "")

    if otype == "Offer":
        p = offers.get("price")
        if p:
            agotado = "InStock" not in offers.get("availability", "")
            return (float(p), False, agotado)
        return (None, True, False)

    if otype == "AggregateOffer":
        individual = offers.get("offers", [])
        if not individual:
            p = offers.get("price")
            return (float(p), False, False) if p else (None, True, False)

        instock = [o for o in individual if "InStock" in o.get("availability", "")]

        # Todos agotados — aplicar mismas estrategias para identificar el variant correcto
        if not instock:
            # Estrategia a-oos: coincidencia por peso o unidades en offer.name
            candidatos_a_oos: list[float] = []
            for o in individual:
                on = str(o.get("name", ""))
                coincide = False
                if peso_nombre_g is not None:
                    ow = _extraer_peso_g(on)
                    if ow is not None and abs(ow - peso_nombre_g) / max(peso_nombre_g, 1) <= TOLERANCIA:
                        coincide = True
                if not coincide and unidades_nombre is not None:
                    ou = _extraer_unidades(on)
                    if ou == unidades_nombre:
                        coincide = True
                if coincide:
                    p_val = o.get("price")
                    if p_val:
                        candidatos_a_oos.append(float(p_val))
            if candidatos_a_oos:
                return (min(candidatos_a_oos), False, True)

            # Estrategia b-oos: size_page ≈ peso_nombre → offers que no contradigan
            if size_page_g is not None and peso_nombre_g is not None:
                if abs(size_page_g - peso_nombre_g) / max(peso_nombre_g, 1) <= TOLERANCIA:
                    candidatos_b_oos: list[float] = []
                    for o in individual:
                        on = str(o.get("name", ""))
                        ow = _extraer_peso_g(on)
                        ou = _extraer_unidades(on)
                        if ow is not None and abs(ow - peso_nombre_g) / max(peso_nombre_g, 1) > TOLERANCIA:
                            continue
                        if ou is not None and unidades_nombre is not None and ou != unidades_nombre:
                            continue
                        p_val = o.get("price")
                        if p_val:
                            candidatos_b_oos.append(float(p_val))
                    if candidatos_b_oos:
                        return (min(candidatos_b_oos), False, True)

            return (None, False, True)  # agotado sin precio identificable

        # Estrategia a: coincidencia por peso o unidades en el nombre del offer
        candidatos_a: list[float] = []
        for o in instock:
            on = str(o.get("name", ""))
            coincide = False
            if peso_nombre_g is not None:
                ow = _extraer_peso_g(on)
                if ow is not None and abs(ow - peso_nombre_g) / max(peso_nombre_g, 1) <= TOLERANCIA:
                    coincide = True
            if not coincide and unidades_nombre is not None:
                ou = _extraer_unidades(on)
                if ou == unidades_nombre:
                    coincide = True
            if coincide:
                p = o.get("price")
                if p:
                    candidatos_a.append(float(p))
        if candidatos_a:
            return (min(candidatos_a), False, False)

        # Estrategia b: el tamaño por defecto de la ficha coincide con el buscado
        # → recoger offers InStock que no contradigan ese tamaño y usar el mínimo
        if size_page_g is not None and peso_nombre_g is not None:
            if abs(size_page_g - peso_nombre_g) / max(peso_nombre_g, 1) <= TOLERANCIA:
                candidatos_b: list[float] = []
                for o in instock:
                    on = str(o.get("name", ""))
                    ow = _extraer_peso_g(on)
                    ou = _extraer_unidades(on)
                    # Excluir offer si tiene un tamaño explícito distinto al buscado
                    if ow is not None and abs(ow - peso_nombre_g) / max(peso_nombre_g, 1) > TOLERANCIA:
                        continue
                    if ou is not None and unidades_nombre is not None and ou != unidades_nombre:
                        continue
                    p = o.get("price")
                    if p:
                        candidatos_b.append(float(p))
                if candidatos_b:
                    return (min(candidatos_b), False, False)

        return (None, True, False)

    return (None, True, False)


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


def _scrape_detalle(url: str, nombre_listing: str = "") -> tuple[str, dict]:
    """
    Visita la página de detalle (caché 7 días) y extrae desde JSON-LD Product:
    - _nombre_completo: nombre con peso incluido (ej "Evowhey protein 2 Kg")
    - _precio_variante: precio correcto de la variante del producto
    - _precio_sin_confirmar: True si no se puede identificar la variante
    - store_rating, store_rating_count, store_rating_url

    nombre_listing: nombre tal como aparece en el listado (incluye peso del producto
    que queremos rastrear), se usa para validar qué variante coincide.

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

                # Precio: resolver la variante correcta en lugar de usar lowPrice
                offers = node.get("offers", {})
                if offers.get("@type"):
                    # Nombre de referencia: preferir el nombre del listado si tiene
                    # peso/unidades extraíbles; si no, usar el nombre del detalle.
                    nombre_completo_local = enrichment.get("_nombre_completo", "")
                    nombre_ref_peso = nombre_listing or nombre_completo_local
                    peso_listing = _extraer_peso_g(nombre_listing) if nombre_listing else None
                    peso_nombre_g = peso_listing or _extraer_peso_g(nombre_completo_local)
                    unidades_nombre = _extraer_unidades(nombre_ref_peso)
                    size_page_g = _extraer_peso_g(node.get("size", ""))
                    precio_v, sin_confirmar, agotado = _resolver_precio_variante(
                        offers, node.get("sku", ""), size_page_g, peso_nombre_g,
                        unidades_nombre,
                    )
                    if precio_v is not None:
                        enrichment["_precio_variante"] = precio_v
                        if agotado:
                            enrichment["_agotado"] = True
                    elif agotado:
                        # Agotado sin precio identificable: flag pero sin precio variante
                        # (el precio del listado se usará como fallback)
                        enrichment["_agotado"] = True
                    elif sin_confirmar:
                        enrichment["_precio_sin_confirmar"] = True
                break
        except Exception:
            pass

    return final_url, enrichment


def _scrape_producto_fijo(url: str, categoria: str, force_fresh: bool = False) -> dict | None:
    """
    Extrae un producto completo (nombre, precio, marca, imagen) desde la página
    de detalle vía JSON-LD Product. Se usa para URLS_FIJAS y catálogo persistente.

    force_fresh=True: ignora la caché y hace petición fresca (necesario para
    recuperación de catálogo, ya que el precio puede haber cambiado).

    Devuelve un dict compatible con el formato de _scrape_listado() o None si falla.
    """
    html = None if force_fresh else get_cached("nutritienda", url)
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
                # Para _scrape_producto_fijo no hay nombre externo de referencia:
                # la variante mostrada en la página (Product.size) es la canónica.
                size_page_g = _extraer_peso_g(node.get("size", ""))
                peso_nombre_g = _extraer_peso_g(nombre_completo) or size_page_g
                unidades_nombre = _extraer_unidades(nombre_completo)
                precio_v, sin_confirmar, agotado = _resolver_precio_variante(
                    offers, node.get("sku", ""), size_page_g, peso_nombre_g, unidades_nombre
                )
                if precio_v is None:
                    if agotado and offers.get("@type"):
                        # Agotado sin precio identificable: usar lowPrice del AggregateOffer
                        fallback = offers.get("lowPrice") or offers.get("price")
                        if fallback:
                            precio_v = float(fallback)
                        else:
                            return None
                    elif sin_confirmar and offers.get("@type"):
                        print(
                            f"  [precio-incierto] {nombre_completo[:50]}: "
                            f"variante no identificable — {url.split('/es/')[-1]}"
                        )
                        return None
                    else:
                        return None
                precio = str(precio_v)

                imagen_raw = node.get("image", "")
                imagen_url = imagen_raw if isinstance(imagen_raw, str) else (imagen_raw[0] if imagen_raw else None)
                if nombre_completo and precio:
                    result = {
                        "nombre":     nombre_completo,
                        "precio":     precio,
                        "marca":      marca_raw,
                        "categoria":  categoria,
                        "url":        final_url,
                        "imagen_url": imagen_url,
                    }
                    if agotado:
                        result["agotado"] = True
                    return result
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
            item_fijo = _scrape_producto_fijo(url_fija, cat_fija, force_fresh=True)
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
        # Siempre fetch fresco: precio puede haber cambiado aunque el producto esté en caché
        time.sleep(DELAY)
        item_fijo = _scrape_producto_fijo(url_cat, meta["categoria"], force_fresh=True)
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
    stats = {"cached": 0, "fetched": 0, "errors": 0, "agotados": 0}

    for i, d in enumerate(productos_raw):
        cached_check = get_cached("nutritienda", d["url"])
        if cached_check is not None:
            stats["cached"] += 1
        else:
            stats["fetched"] += 1

        final_url, enrichment = _scrape_detalle(d["url"], nombre_listing=d["nombre"])
        if not enrichment and cached_check is None:
            stats["errors"] += 1

        # Usar nombre completo del detalle; si no tiene peso, añadir el campo size
        nombre = enrichment.pop("_nombre_completo", d["nombre"])
        size_raw = enrichment.pop("_size", "")
        if size_raw and not re.search(r"\d+\s*(kg|g)\b", nombre, re.IGNORECASE):
            # Normalizar "2270 g" → "2270g", "2 Kg" → "2kg"
            size_norm = re.sub(r"\s+", "", size_raw).lower()
            nombre = f"{nombre} {size_norm}"

        # Precio resuelto por variante (reemplaza el precio de listado si está disponible)
        precio_variante = enrichment.pop("_precio_variante", None)
        sin_confirmar = enrichment.pop("_precio_sin_confirmar", False)
        # _agotado viene del detalle; agotado puede venir del raw dict (_scrape_producto_fijo)
        agotado_flag = enrichment.pop("_agotado", False) or d.get("agotado", False)

        if precio_variante is None and sin_confirmar:
            # No se pudo identificar la variante → no publicar precio
            print(f"  [precio-incierto] SKIP {nombre[:55]}: variante no identificable")
            stats["errors"] += 1
            continue

        precio_str = str(precio_variante) if precio_variante is not None else d["precio"]

        prod = producto_base(
            nombre,
            precio_str,
            d["marca"],
            d["categoria"],
            TIENDA,
            final_url,
            d.get("imagen_url"),
        )
        prod.update(enrichment)
        if agotado_flag:
            prod["agotado"] = True
            stats["agotados"] += 1
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
        f"{stats['cached']} desde caché, {stats['errors']} errores, "
        f"{stats['agotados']} agotados"
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
