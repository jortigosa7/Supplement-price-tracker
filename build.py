"""
build.py — Generador del sitio web estático para SuplementosPrecio.es
======================================================================

Lee el dataset más reciente de datasets/, convierte al schema web,
y genera HTML estático en docs/ listo para publicar en GitHub Pages.

Uso:
    python build.py

Salida:
    data/products.json          (schema web multi-tienda)
    docs/index.html             (home)
    docs/proteina-whey/index.html
    docs/creatina/index.html
    docs/bcaa/index.html
    docs/pre-entreno/index.html
    docs/sitemap.xml
    docs/robots.txt
    docs/.nojekyll
"""

import json
import os
import re
import sys
import glob
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# Forzar UTF-8 en stdout (necesario en Windows con cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# CONFIGURACIÓN — cambia SITE_URL cuando tengas dominio
# ============================================================

SITE_URL    = "https://jortigosa7.github.io/Supplement-price-tracker"
SITE_NAME   = "SuplementosPrecio.es"
DATASETS_DIR = "datasets"
DATA_DIR     = "data"
DOCS_DIR     = "docs"
TEMPLATES_DIR = "templates"

# ============================================================
# CONFIGURACIÓN DE CATEGORÍAS
# ============================================================

CATEGORIA_CONFIG = {
    "Proteínas Whey": {
        "slug":     "proteina-whey",
        "display":  "Proteína Whey",
        "icono":    "🥛",
        "seo_title": "Mejor Precio Proteína Whey España 2026",
        "seo_desc":  "Compara precios de proteína whey en las principales tiendas de España. "
                     "Todos los productos ordenados por precio/kg para encontrar la mejor oferta.",
        "keywords":  "mejor precio proteína whey España, comprar whey barato, "
                     "proteína whey oferta España, whey protein precio",
        "h1":    "Mejor Precio Proteína Whey España",
        "intro": "Comparativa actualizada de proteínas whey disponibles en tiendas españolas. "
                 "Ordenado por precio/kg para que siempre pagues lo justo, sin importar el tamaño del bote.",
    },
    "Creatina": {
        "slug":     "creatina",
        "display":  "Creatina",
        "icono":    "⚡",
        "seo_title": "Mejor Precio Creatina España 2026",
        "seo_desc":  "Compara precios de creatina monohidrato y otras formas en tiendas españolas. "
                     "Encuentra la creatina más barata al mejor precio/kg.",
        "keywords":  "mejor precio creatina España, comprar creatina barata, "
                     "creatina monohidrato oferta, creatina precio España",
        "h1":    "Mejor Precio Creatina España",
        "intro": "Comparativa de creatina en tiendas españolas. "
                 "La creatina monohidrato es el suplemento más estudiado — aquí encuentras la opción más económica.",
    },
    "BCAA": {
        "slug":     "bcaa",
        "display":  "BCAA",
        "icono":    "💊",
        "seo_title": "Mejor Precio BCAA España 2026",
        "seo_desc":  "Compara precios de BCAA y aminoácidos ramificados en tiendas españolas. "
                     "Encuentra los BCAA más baratos por kilogramo.",
        "keywords":  "mejor precio BCAA España, comprar BCAA barato, "
                     "aminoácidos ramificados precio, BCAA oferta España",
        "h1":    "Mejor Precio BCAA España",
        "intro": "Comparativa de BCAA (aminoácidos ramificados) disponibles en tiendas españolas. "
                 "Ordenado por precio/kg, comparando tanto polvo como cápsulas.",
    },
    "Pre-Entreno": {
        "slug":     "pre-entreno",
        "display":  "Pre-Entreno",
        "icono":    "🔥",
        "seo_title": "Mejor Precio Pre-Entreno España 2026",
        "seo_desc":  "Compara precios de suplementos pre-entreno en tiendas españolas. "
                     "Encuentra el mejor pre-workout al precio más bajo.",
        "keywords":  "mejor precio pre-entreno España, comprar pre-workout barato, "
                     "pre-entreno oferta España, mejor pre-workout precio",
        "h1":    "Mejor Precio Pre-Entreno España",
        "intro": "Comparativa de pre-entrenos disponibles en tiendas españolas. "
                 "Ordenado por precio/kg para que compares con criterio.",
    },
}

# Categorías que no están en el config se mapean al slug más cercano
CATEGORIA_FALLBACK_SLUG = "otros"


# ============================================================
# PASO 1: Cargar dataset existente
# ============================================================

def cargar_dataset_mas_reciente() -> list[dict]:
    """Carga el JSON más reciente de la carpeta datasets/."""
    patron = os.path.join(DATASETS_DIR, "suplementos_*.json")
    ficheros = sorted(glob.glob(patron), reverse=True)

    if not ficheros:
        raise FileNotFoundError(
            f"No se encontró ningún fichero JSON en '{DATASETS_DIR}/'. "
            "Ejecuta primero python scraper.py"
        )

    fichero = ficheros[0]
    print(f"📂 Cargando dataset: {fichero}")

    with open(fichero, encoding="utf-8") as f:
        data = json.load(f)

    print(f"   → {len(data)} productos cargados")
    return data, fichero


# ============================================================
# PASO 2: Convertir al schema web (multi-tienda)
# ============================================================

def slugify(texto: str) -> str:
    """Convierte texto a slug URL-friendly."""
    texto = texto.lower().strip()
    reemplazos = {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n","ü":"u"}
    for origen, destino in reemplazos.items():
        texto = texto.replace(origen, destino)
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    texto = texto.strip("-")
    return texto


def convertir_a_schema_web(productos_flat: list[dict]) -> list[dict]:
    """
    Convierte el dataset plano al schema web con precios[] por tienda.
    Usa matching.py para agrupar productos del mismo tipo entre tiendas.
    """
    from matching import agrupar_productos

    # El dataset plano ya tiene precio_eur y peso_kg (viene de limpiar_dataset).
    # agrupar_productos espera el campo "precio" en texto; le pasamos precio_eur
    # como string para que limpiar_precio() lo procese sin pérdida.
    productos_para_matching = []
    for p in productos_flat:
        productos_para_matching.append({
            "nombre":        p.get("nombre", ""),
            "precio":        str(p.get("precio_eur", "N/A")),
            "marca":         p.get("marca", ""),
            "categoria":     p.get("categoria", ""),
            "tienda":        p.get("tienda", ""),
            "url":           p.get("url", "#"),
            "fecha_scraping": p.get("fecha_scraping", ""),
            # peso ya calculado — lo pasamos para no recalcular
            "peso_kg":       p.get("peso_kg"),
        })

    grupos = agrupar_productos(productos_para_matching)

    # Enriquecer con slug de categoría y categoria_display
    productos_web = []
    for g in grupos:
        cat_raw    = g["categoria"]
        cat_config = CATEGORIA_CONFIG.get(cat_raw, {})
        # Si la categoría ya está en slug form (e.g. "Proteinas Whey"), buscar por display también
        if not cat_config:
            for cfg_key, cfg_val in CATEGORIA_CONFIG.items():
                if cfg_val.get("slug") == cat_raw or slugify(cfg_key) == slugify(cat_raw):
                    cat_config = cfg_val
                    break

        cat_slug    = cat_config.get("slug", slugify(cat_raw))
        cat_display = cat_config.get("display", cat_raw)

        productos_web.append({
            "id":                  f"{slugify(g['nombre_normalizado'])}-{slugify(g['marca'])}"[:80],
            "nombre_normalizado":  g["nombre_normalizado"],
            "categoria":           cat_slug,
            "categoria_display":   cat_display,
            "marca":               g["marca"],
            "peso_kg":             g["peso_kg"],
            "precio_por_kg_min":   g.get("precio_por_kg_min"),
            "precio_min":          g.get("precio_min"),
            "tienda_mas_barata":   g.get("tienda_mas_barata"),
            "precios":             g["precios"],
        })

    # Ordenar por categoria slug + precio_por_kg
    productos_web.sort(key=lambda p: (
        p["categoria"],
        p["precio_por_kg_min"] if p["precio_por_kg_min"] is not None else 9999
    ))

    return productos_web


def guardar_products_json(productos_web: list[dict]):
    """Guarda data/products.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "products.json")

    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "site": SITE_NAME,
        "total": len(productos_web),
        "products": productos_web,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"💾 Guardado: {path} ({len(productos_web)} productos)")
    return path


# ============================================================
# PASO 3: Generar HTML con Jinja2
# ============================================================

def setup_jinja():
    """Configura el entorno Jinja2."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
    )
    return env


def contexto_base(last_updated: str) -> dict:
    """Contexto común a todas las páginas."""
    return {
        "site_url":    SITE_URL,
        "site_name":   SITE_NAME,
        "last_updated": last_updated,
        "active_slug": None,
    }


def generar_home(env, productos_web: list[dict], last_updated: str):
    """Genera docs/index.html."""
    template = env.get_template("home.html")

    # Estadísticas para el hero
    tiendas = set()
    for p in productos_web:
        for pr in p["precios"]:
            tiendas.add(pr["tienda"])

    # Datos de categorías para las tarjetas
    categories = []
    for cat_raw, cfg in CATEGORIA_CONFIG.items():
        prods_cat = [p for p in productos_web if p["categoria"] == cfg["slug"]]
        if not prods_cat:
            continue
        precios_kg = [p["precio_por_kg_min"] for p in prods_cat if p["precio_por_kg_min"]]
        categories.append({
            **cfg,
            "count":     len(prods_cat),
            "precio_min": min(precios_kg) if precios_kg else 0,
        })

    # Top 10 por precio/kg
    con_precio_kg = [p for p in productos_web if p["precio_por_kg_min"] is not None]
    top_deals = sorted(con_precio_kg, key=lambda p: p["precio_por_kg_min"])[:10]

    ctx = {
        **contexto_base(last_updated),
        "total_productos": len(productos_web),
        "total_tiendas":   len(tiendas),
        "categories":      categories,
        "top_deals":       top_deals,
    }

    html = template.render(**ctx)
    path = os.path.join(DOCS_DIR, "index.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Generado: {path}")


def generar_categoria(env, cat_raw: str, cfg: dict, productos_web: list[dict], last_updated: str):
    """Genera docs/{slug}/index.html para una categoría."""
    template = env.get_template("category.html")

    prods_cat = [p for p in productos_web if p["categoria"] == cfg["slug"]]

    # Ya vienen ordenados por precio_por_kg desde convertir_a_schema_web
    tiendas = sorted(set(
        pr["tienda"]
        for p in prods_cat
        for pr in p["precios"]
    ))

    ctx = {
        **contexto_base(last_updated),
        "active_slug": cfg["slug"],
        "cat":         cfg,
        "products":    prods_cat,
        "tiendas":     tiendas,
    }

    html = template.render(**ctx)

    outdir = os.path.join(DOCS_DIR, cfg["slug"])
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Generado: {path}  ({len(prods_cat)} productos)")


# ============================================================
# PASO 4: Sitemap y robots.txt
# ============================================================

def generar_sitemap(last_updated: str):
    """Genera docs/sitemap.xml."""
    urls = [
        {"loc": f"{SITE_URL}/",             "priority": "1.0", "changefreq": "weekly"},
    ]
    for cfg in CATEGORIA_CONFIG.values():
        urls.append({
            "loc":        f"{SITE_URL}/{cfg['slug']}/",
            "priority":   "0.8",
            "changefreq": "weekly",
        })

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for u in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{u['loc']}</loc>")
        lines.append(f"    <lastmod>{last_updated}</lastmod>")
        lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        lines.append(f"    <priority>{u['priority']}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")

    path = os.path.join(DOCS_DIR, "sitemap.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Generado: {path}")


def generar_robots():
    """Genera docs/robots.txt."""
    contenido = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    path = os.path.join(DOCS_DIR, "robots.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(contenido)
    print(f"✅ Generado: {path}")


def generar_nojekyll():
    """GitHub Pages ignora carpetas con guión si no existe .nojekyll."""
    path = os.path.join(DOCS_DIR, ".nojekyll")
    with open(path, "w") as f:
        f.write("")
    print(f"✅ Generado: {path}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 54)
    print("  BUILD.PY - Generador de sitio estatico")
    print("=" * 54)
    inicio = datetime.now()

    # 1. Cargar dataset
    productos_flat, fichero_origen = cargar_dataset_mas_reciente()

    # Extraer fecha del nombre del fichero o usar la del primer producto
    last_updated = datetime.now().strftime("%Y-%m-%d")
    if productos_flat:
        last_updated = productos_flat[0].get("fecha_scraping", last_updated)

    # 2. Convertir schema
    print("\n🔄 Convirtiendo al schema web...")
    productos_web = convertir_a_schema_web(productos_flat)
    print(f"   → {len(productos_web)} productos en nuevo schema")

    # Stats por categoría
    for cfg in CATEGORIA_CONFIG.values():
        n = sum(1 for p in productos_web if p["categoria"] == cfg["slug"])
        print(f"   • {cfg['display']}: {n} productos")

    # 3. Guardar products.json
    print()
    guardar_products_json(productos_web)

    # 4. Generar HTML
    print("\n🏗️  Generando HTML...")
    env = setup_jinja()

    generar_home(env, productos_web, last_updated)

    for cat_raw, cfg in CATEGORIA_CONFIG.items():
        generar_categoria(env, cat_raw, cfg, productos_web, last_updated)

    # 5. Sitemap, robots, .nojekyll
    print("\n📋 Generando ficheros auxiliares...")
    generar_sitemap(last_updated)
    generar_robots()
    generar_nojekyll()

    duracion = (datetime.now() - inicio).total_seconds()
    total_paginas = 1 + len(CATEGORIA_CONFIG)

    print("\n" + "=" * 54)
    print(f"  BUILD COMPLETADO en {duracion:.1f}s")
    print(f"  {total_paginas} paginas HTML generadas en docs/")
    print(f"  {len(productos_web)} productos  |  {last_updated}")
    print()
    print("  SIGUIENTE PASO:")
    print('  git add docs/ data/ && git commit -m "build: update site"')
    print("  git push origin master")
    print("  -> Activa GitHub Pages: Settings > Pages > docs/")
    print("=" * 54)
