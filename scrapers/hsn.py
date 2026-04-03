"""
scrapers/hsn.py — Scraper para HSN Store (hsnstore.com)

La web usa Hyva/Magento2 con Alpine.js (SPA), requiere Playwright para
renderizar el JS antes de extraer productos.

SETUP (una sola vez):
    pip install playwright
    playwright install chromium

DEBUG (si no encuentra productos):
    python scraper.py --debug-hsn
    Abre los ficheros debug_hsn_*.html en el navegador e inspecciona
    las clases CSS del contenedor de producto.
"""

import time
from .base import producto_base

TIENDA   = "HSN"
BASE_URL = "https://www.hsnstore.com"
DELAY    = 3  # segundos entre peticiones

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/whey"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/nutricion-deportiva/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/nutricion-deportiva/aminoacidos/bcaa-s-ramificados"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/nutricion-deportiva/pre-entrenamiento"},
]

# JavaScript que se evalúa en el DOM renderizado para extraer productos.
# Prueba múltiples selectores en orden: el primero que devuelva items gana.
_JS_EXTRAER = """
() => {
    const ITEM_SELECTORS = [
        'form.product-item',   // HSN Hyva/Magento2: contenedor es un <form>
        'li.product-item',
        'li.item.product',
        'div.product-item',
    ];

    const NAME_SELECTORS = [
        'a.product-item-link',
        '.product-item-name a',
        '.product-name a',
        'strong.product-item-name a',
        'h2 a', 'h3 a',
    ];

    const PRICE_SELECTORS = [
        '[data-price-type="finalPrice"] .price',
        '.price-final_price .price',
        '.price-box .price',
        'span.price',
        '[class*="price"]',
    ];

    function queryFirst(root, selectors) {
        for (const sel of selectors) {
            try {
                const el = root.querySelector(sel);
                if (el) return el;
            } catch(e) {}
        }
        return null;
    }

    // Encuentra contenedor de productos
    let items = [];
    for (const sel of ITEM_SELECTORS) {
        try {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) { items = Array.from(found); break; }
        } catch(e) {}
    }

    const productos = [];
    for (const item of items) {
        const linkEl  = queryFirst(item, NAME_SELECTORS);
        if (!linkEl) continue;

        const nombre = linkEl.textContent.trim();
        const url    = linkEl.href || '';
        if (!nombre || !url) continue;

        const precioEl = queryFirst(item, PRICE_SELECTORS);
        const precio   = precioEl ? precioEl.textContent.trim() : 'N/A';

        productos.push({ nombre, precio, marca: '', url });
    }

    return { items_found: items.length, productos };
}
"""

# JavaScript para obtener URL de siguiente página (paginación Magento2)
_JS_SIGUIENTE = """
() => {
    const NEXT_SELECTORS = [
        'a.action.next',
        'li.pages-item-next a',
        'a[title="Siguiente"]',
        'a[title="Next"]',
        '.pages .next',
        'a[rel="next"]',
    ];
    for (const sel of NEXT_SELECTORS) {
        try {
            const el = document.querySelector(sel);
            if (el && el.href) return el.href;
        } catch(e) {}
    }
    return null;
}
"""


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
            url_actual = cat["url"]
            pagina = 1

            while url_actual:
                print(f"  Página {pagina}: {url_actual}")
                try:
                    page.goto(url_actual, wait_until="load", timeout=45000)
                    # Espera extra para Alpine.js + scroll para lazy-load
                    page.wait_for_timeout(3000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
                    page.wait_for_timeout(1000)

                    if debug:
                        slug = cat["nombre"].lower().replace(" ", "_")
                        fname = f"debug_hsn_{slug}_p{pagina}.html"
                        with open(fname, "w", encoding="utf-8") as f:
                            f.write(page.content())
                        print(f"  [DEBUG] HTML guardado → {fname}")
                        break  # solo guarda la primera página en debug

                    resultado = page.evaluate(_JS_EXTRAER)
                    nuevos_raw = resultado.get("productos", [])

                    if not nuevos_raw:
                        print(f"  Sin productos (items_found={resultado.get('items_found', 0)}).")
                        print(f"  Tip: python scraper.py --debug-hsn  para inspeccionar el HTML")
                        break

                    nuevos = [
                        producto_base(
                            d["nombre"], d["precio"], d["marca"],
                            cat["nombre"], TIENDA, d["url"]
                        )
                        for d in nuevos_raw if d.get("nombre")
                    ]
                    print(f"  +{len(nuevos)} productos (acumulado: {len(productos) + len(nuevos)})")
                    productos.extend(nuevos)

                    # Siguiente página
                    url_actual = page.evaluate(_JS_SIGUIENTE)
                    pagina += 1
                    if url_actual:
                        time.sleep(DELAY)

                except Exception as e:
                    print(f"  Error en {url_actual}: {e}")
                    break

            time.sleep(DELAY)

        browser.close()

    print(f"\n  Total HSN: {len(productos)} productos")
    return productos
