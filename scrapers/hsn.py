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

import re
import time
from .base import producto_base

TIENDA   = "HSN"
BASE_URL = "https://www.hsnstore.com"
DELAY    = 2  # segundos entre peticiones

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": f"{BASE_URL}/nutricion-deportiva/proteinas/whey"},
    {"nombre": "Creatina",       "url": f"{BASE_URL}/nutricion-deportiva/creatina"},
    {"nombre": "BCAA",           "url": f"{BASE_URL}/nutricion-deportiva/aminoacidos/bcaa-s-ramificados"},
    {"nombre": "Pre-Entreno",    "url": f"{BASE_URL}/nutricion-deportiva/pre-entrenamiento"},
]

# Extrae productos del listado de categoría.
# Selectores confirmados inspeccionando el HTML renderizado por Playwright.
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
        'span[data-price-type] .price',
        '.price-final_price .price',
        '.price-box .price',
        'span.price',
    ];

    function queryFirst(root, selectors) {
        for (const sel of selectors) {
            try { const el = root.querySelector(sel); if (el) return el; } catch(e) {}
        }
        return null;
    }

    let items = [];
    for (const sel of ITEM_SELECTORS) {
        try {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) { items = Array.from(found); break; }
        } catch(e) {}
    }

    const IMG_SELECTORS = [
        'img.product-image-photo',
        '.product-image-wrapper img',
        '.product-image img',
        'img[src*="catalog/product"]',
        'img[src*="media"]',
    ];

    const productos = [];
    for (const item of items) {
        const linkEl = queryFirst(item, NAME_SELECTORS);
        if (!linkEl) continue;
        const nombre = linkEl.textContent.trim();
        const url    = linkEl.href || '';
        if (!nombre || !url) continue;
        const precioEl = queryFirst(item, PRICE_SELECTORS);
        const precio   = precioEl ? precioEl.textContent.trim() : 'N/A';
        let imagen_url = null;
        const imgEl = queryFirst(item, IMG_SELECTORS);
        if (imgEl) {
            const src = imgEl.dataset.src || imgEl.getAttribute('data-original') || imgEl.src || '';
            if (src && src.startsWith('http')) imagen_url = src;
        }
        productos.push({ nombre, precio, url, imagen_url });
    }
    return { items_found: items.length, productos };
}
"""

# Extrae las tallas/pesos disponibles desde la página de detalle del producto.
# #selectProductSimple tiene opciones como "EVOLATE 2.0 500g CHOCOLATE".
_JS_TALLAS = """
() => {
    const sel = document.querySelector('#selectProductSimple');
    if (!sel) return [];
    const texts = Array.from(sel.options).map(o => o.text);
    const sizes = new Set();
    for (const t of texts) {
        const m = t.match(/\\b(\\d+(?:[.,]\\d+)?\\s*(?:kg|g|ml))\\b/gi);
        if (m) m.forEach(s => sizes.add(s.trim()));
    }
    return Array.from(sizes);
}
"""

# URL de la siguiente página (paginación Magento2)
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


def _peso_minimo_kg(tallas: list[str]) -> float | None:
    """Convierte una lista de tallas ['500g', '1Kg', '2Kg'] al peso mínimo en kg."""
    pesos = []
    for t in tallas:
        m = re.match(r"([\d.,]+)\s*(kg|g|ml)", t, re.I)
        if not m:
            continue
        valor = float(m.group(1).replace(",", "."))
        unidad = m.group(2).lower()
        if unidad == "g":
            valor /= 1000
        elif unidad == "ml":
            valor /= 1000
        pesos.append(valor)
    return min(pesos) if pesos else None


def _talla_str(peso_kg: float) -> str:
    """0.5 → '500g',  1.0 → '1kg',  2.27 → '2.27kg'"""
    if peso_kg < 1:
        return f"{round(peso_kg * 1000)}g"
    return f"{peso_kg:g}kg"


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

    productos_raw = []  # sin peso todavía

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

        # ── Paso 1: scraping de listados de categoría ──────────────────────
        for cat in CATEGORIAS:
            print(f"\n  Categoria: {cat['nombre']}")
            url_actual = cat["url"]
            pagina = 1

            while url_actual:
                print(f"  Página {pagina}: {url_actual}")
                try:
                    page.goto(url_actual, wait_until="load", timeout=45000)
                    page.wait_for_timeout(3000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
                    page.wait_for_timeout(1000)

                    if debug:
                        slug = cat["nombre"].lower().replace(" ", "_")
                        fname = f"debug_hsn_{slug}_p{pagina}.html"
                        with open(fname, "w", encoding="utf-8") as f:
                            f.write(page.content())
                        print(f"  [DEBUG] HTML guardado → {fname}")
                        break

                    resultado = page.evaluate(_JS_EXTRAER)
                    nuevos_raw = resultado.get("productos", [])

                    if not nuevos_raw:
                        print(f"  Sin productos (items_found={resultado.get('items_found', 0)}).")
                        print(f"  Tip: python scraper.py --debug-hsn  para inspeccionar el HTML")
                        break

                    for d in nuevos_raw:
                        if d.get("nombre"):
                            productos_raw.append({
                                "nombre":     d["nombre"],
                                "precio":     d["precio"],
                                "categoria":  cat["nombre"],
                                "url":        d["url"],
                                "imagen_url": d.get("imagen_url"),
                            })

                    print(f"  +{len(nuevos_raw)} productos (acumulado: {len(productos_raw)})")

                    url_actual = page.evaluate(_JS_SIGUIENTE)
                    pagina += 1
                    if url_actual:
                        time.sleep(DELAY)

                except Exception as e:
                    print(f"  Error en {url_actual}: {e}")
                    break

            time.sleep(DELAY)

        if debug:
            browser.close()
            return []

        # ── Paso 2: visitar cada producto para obtener el peso ─────────────
        print(f"\n  Obteniendo pesos ({len(productos_raw)} productos)...")
        productos = []

        for i, d in enumerate(productos_raw):
            nombre_con_peso = d["nombre"]
            try:
                page.goto(d["url"], wait_until="load", timeout=30000)
                page.wait_for_timeout(1500)

                tallas = page.evaluate(_JS_TALLAS)
                peso_kg = _peso_minimo_kg(tallas)

                if peso_kg:
                    nombre_con_peso = f"{d['nombre']} {_talla_str(peso_kg)}"

            except Exception as e:
                pass  # sin peso — limpieza.py dejará precio_por_kg=None

            productos.append(
                producto_base(nombre_con_peso, d["precio"], "", d["categoria"], TIENDA, d["url"], d.get("imagen_url"))
            )

            if (i + 1) % 10 == 0:
                print(f"  ... {i+1}/{len(productos_raw)}")
            time.sleep(1)

        browser.close()

    print(f"\n  Total HSN: {len(productos)} productos")
    return productos
