"""
scrapers/hivital.py — Scraper para Hivital.com
Usa la WooCommerce Store API pública (/wp-json/wc/store/v1/products).
Si la API devuelve 0 productos, fallback a JSON-LD de fichas conocidas.

Monetización: enlaces de afiliado Awin (cread.php, MID 20039).
"""

import datetime
import json
import re
import time
import unicodedata
import urllib.parse

import requests
from bs4 import BeautifulSoup

from .base import hacer_peticion, producto_base

TIENDA     = "Hivital"
AWIN_MID   = "20039"
AWIN_AFFID = "2845182"
DELAY      = 1  # segundos entre páginas

WC_API = "https://www.hivital.com/wp-json/wc/store/v1/products"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StackFit/1.0)"}

# URLs de producto conocidas para fallback si la API falla
FALLBACK_URLS = [
    ("https://www.hivital.com/producto/proteina-whey/",    "Proteinas Whey"),
    ("https://www.hivital.com/producto/proteina-isolada/", "Proteinas Whey"),
    ("https://www.hivital.com/producto/proteina-vegana/",  "Proteinas Whey"),
    ("https://www.hivital.com/producto/creatina/",         "Creatina"),
    ("https://www.hivital.com/producto/bcaa/",             "BCAA"),
]

# (regex_en_nombre_limpio, categoria_interna)
_WHITELIST = [
    (re.compile(r'proteina.+(?:whey|suero|concentrad|aislad|isolat|vegana|guisante|arroz)', re.I), "Proteinas Whey"),
    (re.compile(r'\bbcaa\b', re.I), "BCAA"),
    (re.compile(r'\bcreatina\b', re.I), "Creatina"),
]


def _limpiar_nombre(nombre: str) -> str:
    """
    Limpia los nombres de Hivital:
    '▷ Creatina 3000 mg | 1 Kg. de polvo vegano' → 'Creatina 3000 mg 1 kg'
    """
    # Strip prefijo de símbolos decorativos
    nombre = re.sub(r'^[▷►→▸]\s*', '', nombre).strip()
    # Reemplazar ' | ' por ' '
    nombre = nombre.replace(' | ', ' ')
    # Quitar trailing ' de polvo vegano' (con posible punto antes)
    nombre = re.sub(r'\.?\s+de polvo vegano\s*$', '', nombre, flags=re.I).strip()
    # Normalizar 'Kg.' → 'kg'
    nombre = re.sub(r'\bKg\.', 'kg', nombre)
    # Normalizar "720 gramos" → "720g" para que extraer_peso_kg lo parsee
    nombre = re.sub(r'(\d+)\s+gramos\b', r'\1g', nombre, flags=re.I)
    return nombre


def _sin_tildes(texto: str) -> str:
    """Quita acentos para que patrones ASCII coincidan con texto acentuado."""
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _categoria_whitelist(nombre_limpio: str):
    """Devuelve la categoría si el nombre matchea la whitelist; None si no."""
    texto = _sin_tildes(nombre_limpio)
    for patron, categoria in _WHITELIST:
        if patron.search(texto):
            return categoria
    return None


def _url_afiliado(url_producto: str) -> str:
    """Genera el enlace de afiliado Awin para una URL de producto de Hivital."""
    return (
        f"https://www.awin1.com/cread.php"
        f"?awinmid={AWIN_MID}&awinaffid={AWIN_AFFID}"
        f"&ued={urllib.parse.quote(url_producto, safe='')}"
    )


def _precio_de_api(item: dict) -> float | None:
    """Extrae precio en euros desde un item de la WC Store API (centavos como string)."""
    precio_cents = item.get("prices", {}).get("price", "")
    try:
        return float(precio_cents) / 100
    except (ValueError, TypeError):
        return None


def _peso_de_atributos(attrs: list[dict]) -> float | None:
    """
    Intenta extraer el peso en kg del valor de un atributo de variación.
    Busca primero atributos de tipo formato/tamaño; si no, prueba el primero.
    """
    CLAVES_TALLA = ("formato", "tamaño", "talla", "size", "weight", "peso", "capacidad")
    candidatos = [
        a.get("value", "")
        for a in attrs
        if any(k in a.get("name", "").lower() for k in CLAVES_TALLA)
    ]
    if not candidatos and attrs:
        candidatos = [attrs[0].get("value", "")]

    for val in candidatos:
        texto = val.lower().replace(",", ".")
        m = re.search(r'(\d+\.?\d*)\s*(kg|g)\b', texto)
        if m:
            num = float(m.group(1))
            return num if m.group(2) == "kg" else num / 1000
    return None


def _get_variaciones(product_id: int) -> list[dict]:
    """
    Obtiene las variaciones de un producto variable vía WC Store API.
    Devuelve lista de dicts con {precio_eur, agotado, peso_kg, label}.
    Devuelve [] si el endpoint no existe o hay error.
    """
    url = f"https://www.hivital.com/wp-json/wc/store/v1/products/{product_id}/variations"
    try:
        resp = requests.get(url, params={"per_page": 100}, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
    except Exception as e:
        print(f"  ERROR variaciones {product_id}: {e}")
        return []

    variaciones = []
    for v in data:
        precio_eur = _precio_de_api(v)
        if precio_eur is None:
            continue
        agotado = not v.get("is_in_stock", True)
        attrs   = v.get("attributes", [])
        peso_kg = _peso_de_atributos(attrs)
        label   = attrs[0].get("value", "") if attrs else ""
        variaciones.append({
            "precio_eur": precio_eur,
            "agotado":    agotado,
            "peso_kg":    peso_kg,
            "label":      label,
        })
    return variaciones


def _items_de_producto(item: dict) -> list[dict]:
    """
    Convierte un item de la WC Store API en uno o varios dicts normalizados.
    Para productos 'simple' devuelve una lista con un elemento.
    Para productos 'variable' devuelve una entrada por variación con precio propio;
    si el endpoint de variaciones no responde, cae de vuelta a prices.price.
    Siempre incluye productos sin stock (agotado=True), nunca los descarta.
    """
    permalink  = item.get("permalink", "")
    nombre_raw = item.get("name", "")
    nombre     = _limpiar_nombre(nombre_raw)
    categoria  = _categoria_whitelist(nombre)
    if not categoria:
        return []

    imagen_url = None
    imagenes   = item.get("images", [])
    if imagenes:
        imagen_url = imagenes[0].get("src")

    url_aff    = _url_afiliado(permalink)
    tipo       = item.get("type", "simple")
    product_id = item.get("id")

    if tipo == "variable" and product_id:
        variaciones = _get_variaciones(product_id)
        if variaciones:
            multi = len(variaciones) > 1
            result = []
            for v in variaciones:
                nombre_var = nombre
                if multi and v["label"]:
                    nombre_var = _limpiar_nombre(f"{nombre} {v['label']}")
                entry = {
                    "nombre":     nombre_var,
                    "precio":     f"{v['precio_eur']:.2f}",
                    "marca":      "Hivital",
                    "categoria":  categoria,
                    "url":        url_aff,
                    "imagen_url": imagen_url,
                }
                if v["agotado"]:
                    entry["agotado"] = True
                result.append(entry)
            return result
        # Fallback si el endpoint de variaciones no responde: usar prices.price
        print(f"  AVISO: variaciones no disponibles para {nombre[:50]}, usando prices.price")

    # Producto simple (o fallback de variable)
    precio_eur = _precio_de_api(item)
    if precio_eur is None:
        return []

    agotado = not item.get("is_in_stock", True)
    entry = {
        "nombre":     nombre,
        "precio":     f"{precio_eur:.2f}",
        "marca":      "Hivital",
        "categoria":  categoria,
        "url":        url_aff,
        "imagen_url": imagen_url,
    }
    if agotado:
        entry["agotado"] = True
    return [entry]


def _scrape_api() -> list[dict]:
    """
    Recorre todas las páginas de la WC Store API.
    Devuelve lista de dicts raw con campos {nombre, precio, marca, categoria, url, imagen_url, ?agotado}.
    """
    productos = []
    pagina    = 1

    print(f"\n  Consultando WC Store API...")

    while True:
        try:
            resp = requests.get(
                WC_API,
                params={"per_page": 20, "page": pagina},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ERROR API página {pagina}: {e}")
            break

        if not data:
            break

        for item in data:
            permalink = item.get("permalink", "")

            # Saltar versiones en inglés (/en/ en la URL)
            if "/en/" in permalink:
                continue

            for entry in _items_de_producto(item):
                productos.append(entry)

        print(f"  Página {pagina}: {len(data)} items API, {len(productos)} acumulados en whitelist")
        pagina += 1
        time.sleep(DELAY)

    return productos


def _scrape_jsonld_url(url: str, categoria: str) -> dict | None:
    """
    Extrae datos de producto desde JSON-LD de una ficha de Hivital.
    Incluye productos sin stock con agotado=True.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data  = json.loads(script.string or "")
                graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
                for node in graph:
                    if node.get("@type") != "Product":
                        continue
                    nombre_raw = node.get("name", "")
                    nombre     = _limpiar_nombre(nombre_raw)
                    if not nombre:
                        continue

                    offers     = node.get("offers", {})
                    precio_raw = offers.get("price") if offers else None
                    if not precio_raw:
                        continue

                    agotado    = "InStock" not in offers.get("availability", "")
                    marca      = node.get("brand", {}).get("name", "") or "Hivital"
                    imagen_raw = node.get("image", "")
                    imagen_url = imagen_raw if isinstance(imagen_raw, str) else (
                        imagen_raw[0] if isinstance(imagen_raw, list) and imagen_raw else None
                    )

                    url_aff = _url_afiliado(url)
                    entry = {
                        "nombre":     nombre,
                        "precio":     str(float(precio_raw)),
                        "marca":      marca,
                        "categoria":  categoria,
                        "url":        url_aff,
                        "imagen_url": imagen_url,
                    }
                    if agotado:
                        entry["agotado"] = True
                    return entry
            except Exception:
                continue
    except Exception as e:
        print(f"  ERROR JSON-LD {url}: {e}")
    return None


def scrape() -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    hoy = datetime.date.today().isoformat()

    # Intentar API primero
    productos_raw = _scrape_api()

    # Fallback a JSON-LD si la API no devolvió nada
    if not productos_raw:
        print(f"  API devolvió 0 productos. Intentando fallback JSON-LD...")
        for url_fb, cat_fb in FALLBACK_URLS:
            time.sleep(DELAY)
            item = _scrape_jsonld_url(url_fb, cat_fb)
            if item:
                productos_raw.append(item)
                print(f"  Fallback OK: {item['nombre'][:60]}")
            else:
                print(f"  Fallback sin resultado: {url_fb}")

    # Construir productos finales con producto_base
    productos: list[dict] = []
    for d in productos_raw:
        prod = producto_base(
            d["nombre"],
            d["precio"],
            d["marca"],
            d["categoria"],
            TIENDA,
            d["url"],
            d.get("imagen_url"),
        )
        if d.get("agotado"):
            prod["agotado"] = True
        productos.append(prod)

    total    = len(productos)
    agotados = sum(1 for p in productos if p.get("agotado"))
    print(f"\n  Total Hivital: {total} productos ({agotados} agotados)")

    if total == 0:
        print(
            "  AVISO: Hivital scraper devolvió 0 productos — "
            "posible cambio de API o tienda sin stock. Revisar."
        )

    return productos
