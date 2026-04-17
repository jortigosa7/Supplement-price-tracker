"""
scrapers/prozis.py — Scraper para Prozis España (prozis.com/es/es)

Usa Playwright (navegador headless) porque requests recibe 429 de Prozis.
Los datos de listado están en wsData (JSON embebido en el HTML SSR Vue).
Las páginas de detalle se visitan con el mismo navegador en serie (no concurrente)
con retry y backoff exponencial, y se cachean 7 días.

Campos extraídos de las páginas de detalle:
  - store_rating       : JSON-LD aggregateRating.ratingValue (escala 0-10) ÷ 2
  - store_rating_count : aggregateRating.reviewCount
  - flavors_available  : inline JSON "flavor":[{"flavorDescription":...}]

Nutritional (protein_per_serving_g, serving_size_g, servings_per_container) NO se
extraen de Prozis: la tabla nutricional se carga client-side y no está disponible
en domcontentloaded. HSN y Nutritienda ya cubren estos campos.

SETUP (una sola vez):
    pip install playwright
    playwright install chromium

DEBUG: python scraper.py --debug-prozis
"""

import json
import re
import time

from .base import producto_base
from .detail_cache import get_cached, save_cache

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

# Máximo de errores/bloqueos consecutivos antes de abandonar detalle para Prozis
_MAX_CONSECUTIVE_ERRORS = 5


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


def _extraer_enriquecimiento_html(html: str, url: str) -> dict:
    """
    Extrae campos de enriquecimiento del HTML de una página de detalle Prozis.

    - store_rating: JSON-LD aggregateRating.ratingValue (escala 0-10).
      NOTA: Prozis puntúa sobre 10 (igual que Nutritienda) → se divide entre 2
      para normalizar a escala 0-5 homogénea con HSN y MyProtein.
    - store_rating_count: aggregateRating.reviewCount
    - flavors_available: inline JSON "flavor":[{"flavorDescription":...}]
    """
    enrichment: dict = {}

    # ── Rating desde JSON-LD ────────────────────────────────────────────────
    # Prozis usa escala 0-10. Se divide entre 2 para normalizar a 0-5.
    # Prozis envuelve el JSON-LD en CDATA: /*<![CDATA[*/ ... /*]]>*/
    # El regex captura el contenido completo incluyendo esos comentarios.
    jld_blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    for raw in jld_blocks:
        # Strip CDATA wrappers: /*<![CDATA[*/ ... /*]]>*/
        raw = re.sub(r'^[\s]*/\*<!\[CDATA\[\*/', '', raw, flags=re.DOTALL)
        raw = re.sub(r'/\*\]\]>\*/[\s]*$', '', raw, flags=re.DOTALL).strip()
        try:
            d = json.loads(raw)
            if d.get("@type") == "Product":
                agg = d.get("aggregateRating", {})
                rv = agg.get("ratingValue")
                rc = agg.get("reviewCount")
                if rv:
                    enrichment["store_rating"] = round(float(rv) / 2, 2)
                if rc:
                    enrichment["store_rating_count"] = int(rc)
                    enrichment["store_rating_url"] = url
                break
        except Exception:
            pass

    # ── Flavors desde JSON inline "flavor":[{...}] ─────────────────────────
    m = re.search(r'"flavor"\s*:\s*(\[.*?\])', html, re.DOTALL)
    if m:
        try:
            flavor_list = json.loads(m.group(1))
            seen: set = set()
            sabores = []
            for f in flavor_list:
                s = f.get("flavorDescription", "").strip()
                if s and s not in seen:
                    seen.add(s)
                    sabores.append(s)
            if sabores:
                enrichment["flavors_available"] = sabores
        except Exception:
            pass

    return enrichment


def _navegar_detalle(page, url: str) -> str | None:
    """
    Navega a la URL de detalle con Playwright y devuelve el HTML renderizado.
    Reintenta hasta 3 veces con backoff exponencial (2s → 4s → 8s).
    Devuelve None si todos los intentos fallan.
    """
    for intento in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            html = page.content()
            # Validación mínima: debe tener JSON-LD o wsData
            if '"@type"' in html or 'wsData":' in html:
                return html
            print(f"    Página vacía en intento {intento+1}/3 ({url[-40:]})")
        except Exception as e:
            print(f"    Error intento {intento+1}/3: {e}")
        backoff = 2 ** (intento + 1)
        print(f"    Esperando {backoff}s...")
        time.sleep(backoff)
    return None


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

    productos_raw: list[dict] = []

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

        # ── Paso 1: listados de categoría ─────────────────────────────────
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
                        prod = item.get("product", item)
                        nombre = prod.get("name", "").strip()
                        if not nombre:
                            continue
                        precio_raw = prod.get("price", "N/A")
                        href = prod.get("url", "")
                        url_prod = href if href.startswith("http") else BASE_URL + href

                        imagen_url = None
                        for campo in ("imageUrl", "image", "thumbnail", "mainImage", "photo"):
                            v = prod.get(campo, "")
                            if v and isinstance(v, str) and v.startswith("http"):
                                imagen_url = v
                                break
                        if not imagen_url:
                            imgs = prod.get("images", [])
                            if imgs and isinstance(imgs, list):
                                first = imgs[0]
                                if isinstance(first, dict):
                                    imagen_url = first.get("url") or first.get("src")
                                elif isinstance(first, str) and first.startswith("http"):
                                    imagen_url = first

                        productos_raw.append({
                            "nombre":     nombre,
                            "precio":     precio_raw,
                            "categoria":  cat["nombre"],
                            "url":        url_prod,
                            "imagen_url": imagen_url,
                        })
                    except Exception as e:
                        print(f"  Error en producto: {e}")

                print(f"  +{len(items)} productos (acumulado: {len(productos_raw)})")

                total_pages = pagination.get("totalPages", 1)
                if pagina < total_pages:
                    pagina += 1
                    time.sleep(DELAY)
                else:
                    break

            time.sleep(DELAY)

        if debug:
            browser.close()
            return []

        # ── Paso 2: páginas de detalle (rating + flavors, en serie) ──────────
        print(f"\n  Enriqueciendo {len(productos_raw)} productos (detalle + caché 7 días)...")
        stats = {"cached": 0, "fetched": 0, "errors": 0}
        errores_consecutivos = 0

        productos: list[dict] = []

        for i, d in enumerate(productos_raw):
            enrichment: dict = {}

            if errores_consecutivos < _MAX_CONSECUTIVE_ERRORS:
                html_cache = get_cached("prozis", d["url"])
                if html_cache is not None:
                    stats["cached"] += 1
                    enrichment = _extraer_enriquecimiento_html(html_cache, d["url"])
                    errores_consecutivos = 0
                else:
                    html_detail = _navegar_detalle(page, d["url"])
                    if html_detail:
                        save_cache("prozis", d["url"], html_detail)
                        enrichment = _extraer_enriquecimiento_html(html_detail, d["url"])
                        stats["fetched"] += 1
                        errores_consecutivos = 0
                        time.sleep(1)
                    else:
                        stats["errors"] += 1
                        errores_consecutivos += 1
                        if errores_consecutivos >= _MAX_CONSECUTIVE_ERRORS:
                            print(
                                f"\n  ⚠️  {_MAX_CONSECUTIVE_ERRORS} errores consecutivos en Prozis detail. "
                                f"Continuando sin enriquecimiento para los restantes."
                            )

            prod = producto_base(
                d["nombre"], d["precio"], "", d["categoria"], TIENDA,
                d["url"], d.get("imagen_url"),
            )
            prod.update(enrichment)
            productos.append(prod)

            if (i + 1) % 10 == 0:
                print(
                    f"  ... {i+1}/{len(productos_raw)} "
                    f"(caché:{stats['cached']} / fetch:{stats['fetched']} / err:{stats['errors']})"
                )

        browser.close()

    print(f"\n  Total {TIENDA}: {len(productos)} productos")
    print(
        f"  Detalle: {stats['fetched']} fetcheados, "
        f"{stats['cached']} desde caché, {stats['errors']} errores"
    )
    return productos
