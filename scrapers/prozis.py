"""
scrapers/prozis.py — Scraper para Prozis España (prozis.com/es-es)
Usa Playwright porque la web es una SPA con JS rendering.

SETUP (una sola vez):
    pip install playwright
    playwright install chromium

SELECTORES — EDITAR ANTES DE USAR:
    Abre https://www.prozis.com/es-es/proteinas/whey en Chrome
    F12 → inspector → click en nombre del producto → anota la clase CSS
    Rellena las constantes de abajo con lo que veas.
"""

import time

# ──────────────────────────────────────────────────────────
# SELECTORES — RELLENAR CON LOS VALORES REALES DE PROZIS
# ──────────────────────────────────────────────────────────
SEL_PRODUCTO = "TODO_contenedor_producto"   # <-- EDITAR
SEL_NOMBRE   = "TODO_nombre_producto"       # <-- EDITAR
SEL_PRECIO   = "TODO_precio_producto"       # <-- EDITAR
SEL_LINK     = "TODO_link_producto"         # <-- EDITAR
# ──────────────────────────────────────────────────────────

TIENDA   = "Prozis"
BASE_URL = "https://www.prozis.com"

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/es-es/proteinas/whey"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/es-es/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/es-es/aminoacidos/bcaa"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/es-es/pre-entreno"},
]


def _selectores_configurados() -> bool:
    return not any(s.startswith("TODO_") for s in [SEL_PRODUCTO, SEL_NOMBRE, SEL_PRECIO, SEL_LINK])


def scrape(debug: bool = False) -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    if not _selectores_configurados():
        print()
        print("  ATENCION: Los selectores CSS de Prozis no estan configurados.")
        print("  Ejecuta: python scraper.py --debug-prozis")
        print("  O abre prozis.com en Chrome, F12, inspector, click en producto.")
        return []

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
        })

        for cat in CATEGORIAS:
            print(f"\n  Categoria: {cat['nombre']}  →  {cat['url']}")
            try:
                page.goto(cat["url"], wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)

                if debug:
                    html = page.content()
                    fname = f"debug_prozis_{cat['nombre'].lower().replace(' ', '_')}.html"
                    with open(fname, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"  [DEBUG] HTML guardado en {fname}")
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
