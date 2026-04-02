"""
scrapers/hsn.py — Scraper para HSN Store (hsnstore.com)
Usa Playwright porque la web es una SPA con JS rendering.

SETUP (una sola vez):
    pip install playwright
    playwright install chromium

SELECTORES — EDITAR ANTES DE USAR:
    Abre https://www.hsnstore.com/proteinas/whey en Chrome
    F12 → inspector → click en nombre del producto → anota la clase CSS
    Rellena las constantes de abajo con lo que veas.

    Si usas --debug, se guarda el HTML en debug_hsn.html para inspeccionarlo.
"""

import time
import sys

# ──────────────────────────────────────────────────────────
# SELECTORES — RELLENAR CON LOS VALORES REALES DE HSN
# ──────────────────────────────────────────────────────────
# Ejemplo: SEL_PRODUCTO = "div.product-item"
SEL_PRODUCTO = "TODO_contenedor_producto"   # <-- EDITAR
SEL_NOMBRE   = "TODO_nombre_producto"       # <-- EDITAR
SEL_PRECIO   = "TODO_precio_producto"       # <-- EDITAR
SEL_LINK     = "TODO_link_producto"         # <-- EDITAR (tag <a>)
# ──────────────────────────────────────────────────────────

TIENDA = "HSN"
BASE_URL = "https://www.hsnstore.com"

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/proteinas/whey"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/aminoacidos/bcaa"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/pre-entrenamiento"},
]


def _selectores_configurados() -> bool:
    return not any(s.startswith("TODO_") for s in [SEL_PRODUCTO, SEL_NOMBRE, SEL_PRECIO, SEL_LINK])


def _scrape_con_playwright(debug: bool = False) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ERROR: Playwright no instalado.")
        print("  Ejecuta: pip install playwright && playwright install chromium")
        return []

    from .base import producto_base

    productos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not debug)
        page = browser.new_page()
        page.set_extra_http_headers({
            "Accept-Language": "es-ES,es;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        })

        for cat in CATEGORIAS:
            print(f"\n  Categoria: {cat['nombre']}  →  {cat['url']}")
            try:
                page.goto(cat["url"], wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)  # espera carga dinámica

                if debug:
                    html = page.content()
                    with open(f"debug_hsn_{cat['nombre'].lower().replace(' ', '_')}.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"  [DEBUG] HTML guardado en debug_hsn_*.html")
                    print(f"  [DEBUG] Abre ese fichero y busca el selector CSS del producto")
                    continue

                items = page.query_selector_all(SEL_PRODUCTO)
                print(f"  Encontrados: {len(items)} contenedores")

                for item in items:
                    try:
                        nombre_el = item.query_selector(SEL_NOMBRE)
                        precio_el = item.query_selector(SEL_PRECIO)
                        link_el   = item.query_selector(SEL_LINK)

                        nombre = nombre_el.inner_text().strip() if nombre_el else None
                        precio = precio_el.inner_text().strip() if precio_el else "N/A"
                        href   = link_el.get_attribute("href") if link_el else ""
                        url    = href if href.startswith("http") else BASE_URL + href

                        if nombre:
                            productos.append(producto_base(nombre, precio, "", cat["nombre"], TIENDA, url))
                    except Exception as e:
                        print(f"  Error en producto: {e}")

                print(f"  Acumulado: {len(productos)}")
                time.sleep(2)

            except Exception as e:
                print(f"  Error cargando {cat['url']}: {e}")

        browser.close()

    return productos


def scrape(debug: bool = False) -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    if not _selectores_configurados():
        print()
        print("  ATENCION: Los selectores CSS de HSN no estan configurados.")
        print("  Pasos para obtenerlos:")
        print("  1. Ejecuta: python scraper.py --debug-hsn")
        print("     (guarda el HTML renderizado en debug_hsn_*.html)")
        print("  2. Abre el fichero en VS Code y busca un nombre de producto")
        print("  3. Anota la clase CSS del contenedor padre")
        print("  4. Edita scrapers/hsn.py y rellena SEL_PRODUCTO, SEL_NOMBRE, etc.")
        print()
        print("  O abre hsnstore.com en Chrome, F12, inspector, click en producto.")
        return []

    return _scrape_con_playwright(debug=debug)
