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
        "guia_titulo": "¿Qué proteína whey comprar en España?",
        "guia_texto": (
            "La proteína whey (suero de leche) es el suplemento más popular para aumentar la ingesta proteica. "
            "Existen tres formas principales: el concentrado (70-80 % proteína, más económico), "
            "el aislado (>90 % proteína, menos lactosa) y el hidrolizado (absorción más rápida, precio más alto). "
            "Para la mayoría de personas, el concentrado o el aislado son más que suficientes. "
            "Lo más importante es elegir por precio/kg y no por tamaño de bote: "
            "un bote de 5 kg puede salir más barato por gramo que uno de 1 kg."
        ),
        "como_comparamos": (
            "Actualizamos los precios varias veces por semana extrayendo datos directamente de las webs de "
            "HSN, MyProtein, Nutritienda y Prozis. Calculamos el precio por kilogramo para que "
            "puedas comparar botes de distintos tamaños de forma justa y encontrar siempre la mejor oferta."
        ),
        "faq": [
            {
                "q": "¿Cuándo tomar proteína whey?",
                "a": "El momento ideal es justo después del entrenamiento, pero lo que más importa es alcanzar tu objetivo proteico diario (1,6–2,2 g por kg de peso corporal). Puedes tomarla en cualquier momento del día.",
            },
            {
                "q": "¿Cuánta proteína whey debo tomar al día?",
                "a": "Lo habitual es una ración de 20–40 g por toma. La cantidad total depende de tu dieta: si no llegas a tus necesidades proteicas con la comida, un batido te ayuda a completarlas.",
            },
            {
                "q": "¿Cuál es la diferencia entre whey concentrada y aislada?",
                "a": "El aislado tiene mayor pureza proteica (>90 %) y prácticamente sin lactosa, ideal si tienes intolerancia. El concentrado es más económico y suficiente para la mayoría.",
            },
            {
                "q": "¿Es mejor comparar por precio por bote o precio/kg?",
                "a": "Siempre por precio/kg. Un bote grande puede parecer caro pero ser mucho más barato por gramo que uno pequeño. Por eso ordenamos todos los productos por €/kg.",
            },
        ],
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
        "guia_titulo": "¿Qué creatina comprar en España?",
        "guia_texto": (
            "La creatina monohidrato es la forma más respaldada científicamente: cientos de estudios confirman "
            "su eficacia para mejorar el rendimiento en esfuerzos de alta intensidad y favorecer la ganancia de "
            "fuerza y masa muscular. Las variantes como la Creapure (micronizada alemana) ofrecen mayor pureza "
            "y mejor solubilidad. Formas más caras como el HCL o el etil éster no han demostrado superioridad. "
            "Compra por precio/kg: la creatina es un commodity y no merece la pena pagar de más."
        ),
        "como_comparamos": (
            "Comparamos precios de creatina monohidrato, Creapure y otras formas en HSN, MyProtein, "
            "Nutritienda y Prozis. El precio/kg es especialmente útil aquí porque los formatos varían "
            "mucho: desde sobres de 300 g hasta botes de 1 kg o más."
        ),
        "faq": [
            {
                "q": "¿Para qué sirve la creatina?",
                "a": "Mejora el rendimiento en ejercicios de alta intensidad y corta duración (sprints, pesas), y favorece la ganancia de fuerza y masa muscular. Es el suplemento deportivo con mayor evidencia científica tras la proteína.",
            },
            {
                "q": "¿Cuánta creatina tomar al día?",
                "a": "3–5 g diarios de creatina monohidrato son suficientes. La fase de carga (20 g/día durante 5–7 días) satura los depósitos más rápido, pero es opcional.",
            },
            {
                "q": "¿Cuándo tomar la creatina?",
                "a": "El timing no es crítico. Lo importante es tomarla todos los días. Puedes tomarla antes o después del entrenamiento, o con el desayuno en días de descanso.",
            },
            {
                "q": "¿La creatina monohidrato es la mejor forma?",
                "a": "Sí, según la evidencia actual. Es la forma más estudiada, eficaz y económica. Las variantes más caras (HCL, tamponada, etil éster) no ofrecen ventajas demostradas.",
            },
        ],
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
        "guia_titulo": "¿Qué BCAA comprar en España?",
        "guia_texto": (
            "Los BCAA (leucina, isoleucina y valina) son los tres aminoácidos ramificados esenciales. "
            "La ratio más común es 2:1:1, aunque también hay versiones 4:1:1 u 8:1:1 con más leucina, "
            "el aminoácido clave para la síntesis proteica. El polvo suele ser más económico por gramo que "
            "las cápsulas. Si ya tomas suficiente proteína de calidad, los BCAA aportan poco valor extra. "
            "Son más útiles si entrenas en ayunas o sigues una dieta baja en proteína animal."
        ),
        "como_comparamos": (
            "Comparamos BCAA en polvo y cápsulas de distintas ratios (2:1:1, 4:1:1, 8:1:1) en HSN, MyProtein, "
            "Nutritienda y Prozis. El precio/kg permite comparar formatos muy distintos de forma justa."
        ),
        "faq": [
            {
                "q": "¿Para qué sirven los BCAA?",
                "a": "Los BCAA reducen la fatiga muscular durante el entrenamiento, protegen el músculo en déficit calórico y estimulan la síntesis proteica gracias a la leucina. Son especialmente útiles entrenando en ayunas.",
            },
            {
                "q": "¿Es mejor tomar BCAA en polvo o en cápsulas?",
                "a": "El polvo suele ser más económico por gramo y permite dosis flexibles. Las cápsulas son más cómodas para llevar. Compara siempre por precio/kg para elegir el formato más rentable.",
            },
            {
                "q": "¿Cuándo tomar BCAA?",
                "a": "Antes o durante el entrenamiento para reducir la fatiga. También son útiles por la mañana si vas a entrenar en ayunas, para proteger la masa muscular.",
            },
            {
                "q": "¿Son necesarios los BCAA si ya tomo proteína whey?",
                "a": "Si consumes suficiente proteína de calidad (1,6–2,2 g/kg/día), los BCAA aportan poco valor adicional ya que la whey ya los contiene en cantidad significativa. Son más útiles en dietas restrictivas.",
            },
        ],
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
        "guia_titulo": "¿Qué pre-entreno comprar en España?",
        "guia_texto": (
            "Los pre-entrenos combinan varios ingredientes activos para mejorar la energía y la concentración. "
            "Los componentes más comunes y respaldados son: cafeína (150–300 mg, estimulante principal), "
            "citrulina malato (pump y resistencia), beta-alanina (retrasa la fatiga muscular) y creatina. "
            "Revisa siempre las dosis en el etiquetado: muchos productos usan 'blend' propietario "
            "sin especificar la cantidad de cada ingrediente."
        ),
        "como_comparamos": (
            "Comparamos pre-entrenos de HSN, MyProtein, Nutritienda y Prozis ordenados por precio/kg. "
            "Ten en cuenta que los pre-entrenos varían mucho en composición: compara ingredientes y dosis "
            "además del precio para tomar la mejor decisión."
        ),
        "faq": [
            {
                "q": "¿Qué contiene un pre-entreno?",
                "a": "Los ingredientes más comunes son cafeína (estimulante), citrulina malato (pump y resistencia), beta-alanina (retrasa la fatiga) y creatina. La calidad depende de las dosis reales de cada ingrediente.",
            },
            {
                "q": "¿Cuándo tomar el pre-entreno?",
                "a": "Entre 20 y 30 minutos antes del entrenamiento, para aprovechar el pico de los estimulantes. La cafeína tarda unos 45 min en alcanzar su máximo efecto en sangre.",
            },
            {
                "q": "¿El pre-entreno es seguro?",
                "a": "Para personas sanas, sí. Evítalo si eres sensible a la cafeína, tienes problemas cardíacos, estás embarazada o entrenas por la noche. Empieza con media dosis para evaluar tu tolerancia.",
            },
            {
                "q": "¿Se puede tomar pre-entreno todos los días?",
                "a": "No es recomendable. El consumo diario genera tolerancia rápida a la cafeína, reduciendo su efecto. Úsalo solo en sesiones clave o con días de descanso entre tomas.",
            },
        ],
    },
}

# Categorías que no están en el config se mapean al slug más cercano
CATEGORIA_FALLBACK_SLUG = "otros"

# Mapa slug Nutritienda → nombre de marca legible
NUTRITIENDA_SLUG_MARCA = {
    "fire-nutrition":           "Fire Nutrition",
    "beverly-nutrition":        "Beverly Nutrition",
    "amix-nutrition":           "Amix Nutrition",
    "amix-performance":         "Amix",
    "bulk":                     "Bulk",
    "big":                      "Big",
    "mega-plus":                "Mega Plus",
    "dedicated-nutrition":      "Dedicated Nutrition",
    "dmi-innovative-nutrition": "DMI Innovative Nutrition",
    "biotech-usa":              "BioTechUSA",
    "life-pro-nutrition":       "Life Pro Nutrition",
    "crown-sport-nutrition":    "Crown Sport Nutrition",
    "perfect-sports":           "Perfect Sports",
}


def corregir_marcas(productos_web: list[dict]) -> list[dict]:
    """
    Corrige la marca 'Desconocida' y unifica variantes incorrectas.
    Se aplica tras el matching para que cada build produzca datos limpios.
    """
    def _marca_desde_urls(urls):
        for url in urls:
            if "nutritienda.com" in url:
                parts = url.rstrip("/").split("/")
                if len(parts) >= 5 and parts[4] not in ("es", "www", ""):
                    slug = parts[4]
                    return NUTRITIENDA_SLUG_MARCA.get(slug, slug.replace("-", " ").title())
        for url in urls:
            if "myprotein." in url:
                return "MyProtein"
        for url in urls:
            if "hsnstore.com" in url:
                return "HSN"
        for url in urls:
            if "prozis.com" in url:
                return "Prozis"
        return None

    # Unificar variantes conocidas
    NORMALIZACIONES = {"Nutrend": "NUTREND"}

    for p in productos_web:
        marca = p.get("marca", "")
        if marca in NORMALIZACIONES:
            p["marca"] = NORMALIZACIONES[marca]
        if p.get("marca") == "Desconocida":
            urls = [pr.get("url_afiliado", "") for pr in p.get("precios", [])]
            nueva = _marca_desde_urls(urls)
            if nueva:
                p["marca"] = nueva

    return productos_web


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

    # Corregir marcas (Desconocida → tienda/slug, unificar variantes)
    productos_web = corregir_marcas(productos_web)

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
        "tiendas_lista":   sorted(tiendas),
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
