"""
scrapers/prozis.py — Scraper para Prozis España (prozis.com/es/es)

Usa Playwright (navegador headless) porque requests recibe 429 de Prozis.
Los datos de producto están embebidos como JSON (wsData) en el HTML SSR Vue.

SETUP (una sola vez):
    pip install playwright
    playwright install chromium

DEBUG: python scraper.py --debug-prozis
"""

import json
import time
from .base import producto_base

TIENDA         = "Prozis"
BASE_URL       = "https://www.prozis.com"
DELAY          = 3
MAX_PAGES      = 5
ITEMS_PER_PAGE = 48

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/es/es/nutricion-deportiva/proteina/proteina-whey"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/es/es/nutricion-deportiva/desarrollo-muscular/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/es/es/nutricion-deportiva/desarrollo-muscular/bcaa"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/es/es/nutricion-deportiva/desarrollo-muscular/preentrenamiento-y-oxido-nitrico"},
]


def _extraer_wsdata(html: str) -> tuple[list[dict], dict]:
    """
    Extrae el objeto wsData embebido en el HTML SSR de Prozis.
    Busca 'wsData":' y parsea el objeto JSON completo.
    Returns: (products_list, pagination_dict)
    """
    decoder = json.JSONDecoder()

    idx = html.find('wsData":')
    if idx == -1:
        return [], {}

    obj_start = html.find('{', idx)
    if obj_start == -1:
        return [], {}

    try:
        obj, _ = decoder.raw_decode(html, obj_start)
    except (json.JSONDecodeError, ValueError):
        return [], {}

    items      = obj.get("results", [])
    pagination = obj.get("pagination", {})
    return items, pagination


def scrape(debug: bool = False) -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ERROR: Playwright no instalado.")
        print("  Ejecuta: pip install playwright && playwright install chromium")
        return []

    productos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-ES",
            extra_http_headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
        )
        page = context.new_page()

        for cat in CATEGORIAS:
            print(f"\n  Categoria: {cat['nombre']}")
            pagina = 1

            while pagina <= MAX_PAGES:
                url = cat["url"] if pagina == 1 else f"{cat['url']}?page={pagina}"
                print(f"  Página {pagina}: {url}")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2500)
                except Exception as e:
                    print(f"  Error cargando página: {e}")
                    break

                html = page.content()

                if debug:
                    slug = cat["nombre"].lower().replace(" ", "_")
                    fname = f"debug_prozis_{slug}_p{pagina}.html"
                    with open(fname, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"  [DEBUG] HTML guardado → {fname}")
                    break

                items, pagination = _extraer_wsdata(html)

                if not items:
                    print(f"  No se encontró wsData.")
                    print(f"  Tip: python scraper.py --debug-prozis  para inspeccionar el HTML")
                    break

                for item in items:
                    try:
                        # Prozis envuelve cada entrada en {"product": {...}}
                        prod = item.get("product", item)
                        nombre = prod.get("name", "").strip()
                        if not nombre:
                            continue
                        precio_raw = prod.get("price", "N/A")
                        href = prod.get("url", "")
                        url_prod = href if href.startswith("http") else BASE_URL + href
                        productos.append(
                            producto_base(nombre, precio_raw, "", cat["nombre"], TIENDA, url_prod)
                        )
                    except Exception as e:
                        print(f"  Error en producto: {e}")

                print(f"  +{len(items)} productos (acumulado: {len(productos)})")

                total_pages = pagination.get("totalPages", 1)
                if pagina < total_pages:
                    pagina += 1
                    time.sleep(DELAY)
                else:
                    break

            time.sleep(DELAY)

        browser.close()

    print(f"\n  Total {TIENDA}: {len(productos)} productos")
    return productos
