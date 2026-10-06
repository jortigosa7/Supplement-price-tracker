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
    ("https://www.hivital.com/producto/glutamina/",        "BCAA"),
]

# (regex_en_nombre_limpio, categoria_interna)
_WHITELIST = [
    (re.compile(r'proteina.+(?:whey|suero|concentrad|aislad|isolat|vegana|guisante|arroz)', re.I), "Proteinas Whey"),
    (re.compile(r'\bbcaa\b', re.I), "BCAA"),
    (re.compile(r'\bglutamin[ae]\b', re.I), "BCAA"),
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
    # Normalizar acentos: "Proteína" → "Proteina" para que coincida con r'proteina'
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


def _scrape_api() -> list[dict]:
    """
    Recorre todas las páginas de la WC Store API.
    Devuelve lista de dicts raw con campos {nombre, precio, marca, categoria, url, imagen_url}.
    """
    productos = []
    pagina = 1

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

            # Saltar productos sin stock
            if not item.get("is_in_stock", True):
                continue

            nombre_raw = item.get("name", "")
            nombre = _limpiar_nombre(nombre_raw)
            categoria = _categoria_whitelist(nombre)
            if not categoria:
                continue

            # Precio: API devuelve centavos como string ("2777" → 27.77)
            precio_cents = item.get("prices", {}).get("price", "")
            try:
                precio_eur = float(precio_cents) / 100
                precio_str = f"{precio_eur:.2f}"
            except (ValueError, TypeError):
                continue

            imagen_url = None
            imagenes = item.get("images", [])
            if imagenes:
                imagen_url = imagenes[0].get("src")

            marca_raw = ""
            # La API no expone marca directamente; se deja vacío para que matching.py la infiera
            # o bien se usa "Hivital" como fallback en matching.
            # Hivital es la única marca que vende en su propia tienda.
            marca_raw = "Hivital"

            url_aff = _url_afiliado(permalink)
            productos.append({
                "nombre":     nombre,
                "precio":     precio_str,
                "marca":      marca_raw,
                "categoria":  categoria,
                "url":        url_aff,
                "imagen_url": imagen_url,
            })

        print(f"  Página {pagina}: {len(data)} items API, {len(productos)} acumulados en whitelist")
        pagina += 1
        time.sleep(DELAY)

    return productos


def _scrape_jsonld_url(url: str, categoria: str) -> dict | None:
    """
    Extrae datos de producto desde JSON-LD de una ficha de Hivital.
    Busca el nodo @type: 'Product' y extrae nombre, precio, marca, imagen.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
                for node in graph:
                    if node.get("@type") != "Product":
                        continue
                    nombre_raw = node.get("name", "")
                    nombre = _limpiar_nombre(nombre_raw)
                    if not nombre:
                        continue

                    offers = node.get("offers", {})
                    precio_raw = offers.get("price") if offers else None
                    if not precio_raw:
                        continue
                    disponibilidad = offers.get("availability", "")
                    if "InStock" not in disponibilidad:
                        continue

                    marca = node.get("brand", {}).get("name", "") or "Hivital"
                    imagen_raw = node.get("image", "")
                    imagen_url = imagen_raw if isinstance(imagen_raw, str) else (
                        imagen_raw[0] if isinstance(imagen_raw, list) and imagen_raw else None
                    )

                    url_aff = _url_afiliado(url)
                    return {
                        "nombre":     nombre,
                        "precio":     str(float(precio_raw)),
                        "marca":      marca,
                        "categoria":  categoria,
                        "url":        url_aff,
                        "imagen_url": imagen_url,
                    }
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
        productos.append(prod)

    total = len(productos)
    print(f"\n  Total Hivital: {total} productos")

    # Guardia suave: Hivital es nueva tienda, no hacemos raise si 0 productos
    if total == 0:
        print(
            "  AVISO: Hivital scraper devolvió 0 productos — "
            "posible cambio de API o tienda sin stock. Revisar."
        )

    return productos
