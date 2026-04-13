"""
build.py — Generador del sitio web estático para StackFit
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

SITE_URL    = "https://stackfit.es"
SITE_NAME   = "StackFit"
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
        "icon_svg": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4h12l-1.5 4H7.5L6 4z"/><path d="M7.5 8c0 0-.5 2-.5 5s.5 5 .5 5h9s.5-2 .5-5-.5-5-.5-5"/><path d="M9 13h6"/></svg>',
        "seo_title": "Mejor Precio Proteína Whey España 2026",
        "seo_desc":  "Compara 63 proteínas whey en España ordenadas por €/kg. "
                     "Encuentra la más barata entre HSN, MyProtein, Nutritienda y Prozis. Precios actualizados.",
        "keywords":  "mejor precio proteína whey España, comprar whey barato, "
                     "proteína whey oferta España, whey protein precio",
        "h1":    "Mejor Precio Proteína Whey España",
        "intro": "Comparativa actualizada de proteínas whey disponibles en tiendas españolas. "
                 "Ordenado por precio/kg para que siempre pagues lo justo, sin importar el tamaño del bote.",
        "guia_titulo": "Cómo elegir la mejor proteína whey por precio/kg",
        "guia_texto": (
            "La proteína whey o suero de leche es el suplemento más popular en el mundo del fitness: "
            "tiene un perfil de aminoácidos completo, se digiere rápido y es muy efectiva para la "
            "recuperación muscular. Pero en el mercado español hay decenas de marcas y formatos, y "
            "los precios varían enormemente.\n\n"
            "¿Concentrada, aislada o hidrolizada? La whey concentrada (WPC) tiene entre un 70-80% de "
            "proteína y es la más económica. La aislada (WPI) supera el 90% de proteína, tiene menos "
            "lactosa y grasa, y es mejor opción si tienes intolerancia a la lactosa. La hidrolizada es "
            "la más cara y se digiere más rápido, aunque las diferencias prácticas son mínimas para la "
            "mayoría de usuarios.\n\n"
            "Cómo leer el precio/kg: comparar por precio de bote es un error habitual. Un bote de 2 kg "
            "a 45 € puede parecer caro frente a uno de 1 kg a 20 €, pero al normalizarlo el primero "
            "sale a 22,50 €/kg y el segundo a 20 €/kg. Además, fíjate en los gramos de proteína por "
            "servicio: no es lo mismo 20 g que 25 g por cacito. Lo ideal es buscar mínimo 20 g de "
            "proteína por servicio y un precio inferior a 20 €/kg.\n\n"
            "¿Cuánto tomar? La evidencia científica sugiere entre 1,6 y 2,2 g de proteína por kilo de "
            "peso corporal al día. La whey es un complemento a tu dieta, no un sustituto. Un batido "
            "post-entreno de 25-30 g es suficiente para la mayoría.\n\n"
            "Qué evitar: productos con mucho azúcar añadido, aminoácidos spike (glicina o taurina "
            "inflando el contenido proteico), o marcas que no publican la composición completa por servicio."
        ),
        "como_comparamos": (
            "Actualizamos los precios varias veces por semana extrayendo datos directamente de las webs de "
            "HSN, MyProtein, Nutritienda y Prozis. Calculamos el precio por kilogramo para que "
            "puedas comparar botes de distintos tamaños de forma justa y encontrar siempre la mejor oferta."
        ),
        "faq": [
            {
                "q": "¿Es mejor la whey aislada que la concentrada?",
                "a": (
                    "Depende de tu objetivo. Si tienes intolerancia a la lactosa o buscas menos calorías, "
                    "la aislada es mejor opción. Para la mayoría, la concentrada ofrece mejor relación "
                    "calidad-precio."
                ),
            },
            {
                "q": "¿Puedo tomar whey si no hago ejercicio?",
                "a": (
                    "Sí, es simplemente proteína de alimento. Pero si no entrenas, mejor obtenerla de "
                    "fuentes naturales como huevos, pollo o legumbres."
                ),
            },
            {
                "q": "¿Cuánto tiempo dura un kilo de whey?",
                "a": "Con un servicio diario de 30 g, aproximadamente 33 días.",
            },
        ],
    },
    "Creatina": {
        "slug":     "creatina",
        "display":  "Creatina",
        "icono":    "⚡",
        "icon_svg": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="7" y="3" width="10" height="18" rx="2"/><path d="M7 8h10"/><path d="M7 16h10"/><path d="M10 11.5h4"/></svg>',
        "seo_title": "Mejor Precio Creatina España 2026",
        "seo_desc":  "Compara creatina monohidrato y Creapure en España por €/kg. "
                     "Los mejores precios entre HSN, MyProtein, Nutritienda y Prozis.",
        "keywords":  "mejor precio creatina España, comprar creatina barata, "
                     "creatina monohidrato oferta, creatina precio España",
        "h1":    "Mejor Precio Creatina España",
        "intro": "Comparativa de creatina en tiendas españolas. "
                 "La creatina monohidrato es el suplemento más estudiado — aquí encuentras la opción más económica.",
        "guia_titulo": "Cómo elegir creatina: guía de compra por precio/kg",
        "guia_texto": (
            "La creatina monohidrato es el suplemento con más evidencia científica detrás después de "
            "la cafeína. Aumenta la fuerza, mejora el rendimiento en ejercicios de alta intensidad y "
            "favorece la recuperación. Y lo mejor: es barata.\n\n"
            "¿Qué tipo de creatina comprar? Olvida el marketing: la creatina monohidrato es la forma "
            "más estudiada y efectiva. Las variantes como creatina HCL, Kre-Alkalyn o etil éster no "
            "han demostrado ser superiores en ningún estudio serio, y cuestan el doble o más.\n\n"
            "Cómo leer el precio/kg: la creatina monohidrato de calidad debería costar entre 15 € y "
            "30 €/kg. Si ves algo más caro sin justificación, estás pagando por marketing. Busca "
            "productos con sello Creapure si quieres garantía de pureza alemana, aunque encarece "
            "el precio.\n\n"
            "Protocolo de uso: no hace falta fase de carga. 3-5 g diarios son suficientes. Tómala "
            "siempre a la misma hora, preferiblemente con carbohidratos o proteína para mejorar la "
            "absorción. Los efectos se notan tras 2-4 semanas de uso continuado.\n\n"
            "Mitos frecuentes: la creatina no daña los riñones en personas sanas, no causa calvicie "
            "y no es un esteroide. Es uno de los suplementos más seguros y estudiados del mercado."
        ),
        "como_comparamos": (
            "Comparamos precios de creatina monohidrato, Creapure y otras formas en HSN, MyProtein, "
            "Nutritienda y Prozis. El precio/kg es especialmente útil aquí porque los formatos varían "
            "mucho: desde sobres de 300 g hasta botes de 1 kg o más."
        ),
        "faq": [
            {
                "q": "¿Hay que hacer fase de carga con creatina?",
                "a": (
                    "No es necesaria. Con 3-5 g diarios llegas al mismo nivel en 3-4 semanas. La carga "
                    "(20 g/día durante 5 días) solo acelera la saturación inicial."
                ),
            },
            {
                "q": "¿Cuándo es mejor tomar la creatina?",
                "a": "El momento importa poco. Lo relevante es la consistencia diaria.",
            },
            {
                "q": "¿La creatina micronizada es mejor que la normal?",
                "a": "Se disuelve mejor en agua, pero el efecto en rendimiento es idéntico a la monohidrato estándar.",
            },
        ],
    },
    "BCAA": {
        "slug":     "bcaa",
        "display":  "BCAA",
        "icono":    "💊",
        "icon_svg": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="9" width="18" height="6" rx="3"/><line x1="12" y1="9" x2="12" y2="15"/></svg>',
        "seo_title": "Mejor Precio BCAA España 2026",
        "seo_desc":  "Compara BCAA 2:1:1 y 4:1:1 en España por €/kg. "
                     "Encuentra el precio más bajo entre las principales tiendas de suplementos.",
        "keywords":  "mejor precio BCAA España, comprar BCAA barato, "
                     "aminoácidos ramificados precio, BCAA oferta España",
        "h1":    "Mejor Precio BCAA España",
        "intro": "Comparativa de BCAA (aminoácidos ramificados) disponibles en tiendas españolas. "
                 "Ordenado por precio/kg, comparando tanto polvo como cápsulas.",
        "guia_titulo": "Guía de compra de BCAA: cuándo valen la pena y cómo comparar por €/kg",
        "guia_texto": (
            "Los BCAA (aminoácidos de cadena ramificada: leucina, isoleucina y valina) son quizás el "
            "suplemento más sobrevendido del mercado fitness. Antes de comprarlos, conviene entender "
            "cuándo tienen sentido y cuándo no.\n\n"
            "¿Los necesitas realmente? Si ya consumes suficiente proteína al día (1,6-2,2 g/kg), "
            "probablemente no. La whey ya contiene BCAA en abundancia. Los BCAA tienen más sentido "
            "si entrenas en ayunas, sigues una dieta vegana con proteína limitada, o buscas reducir "
            "el catabolismo en déficit calórico severo.\n\n"
            "Ratio 2:1:1 vs 4:1:1 vs 8:1:1: el ratio indica la proporción de leucina respecto a "
            "isoleucina y valina. La leucina es el aminoácido más anabólico, pero subir el ratio no "
            "siempre mejora resultados. El 2:1:1 es el más estudiado y el más equilibrado.\n\n"
            "Precio/kg y dosis: una dosis típica son 5-10 g por toma. Al comparar por €/kg, productos "
            "similares pueden variar entre 20 € y 60 €/kg. No tiene sentido pagar el triple por el "
            "mismo compuesto. Mira la cantidad de leucina por servicio: busca al menos 2,5 g.\n\n"
            "Sabores y formatos: los BCAA en polvo con sabor son cómodos para tomar durante el "
            "entrenamiento. Los sin sabor son más versátiles pero algunos tienen un gusto amargo pronunciado."
        ),
        "como_comparamos": (
            "Comparamos BCAA en polvo y cápsulas de distintas ratios (2:1:1, 4:1:1, 8:1:1) en HSN, MyProtein, "
            "Nutritienda y Prozis. El precio/kg permite comparar formatos muy distintos de forma justa."
        ),
        "faq": [
            {
                "q": "¿BCAA o proteína whey, cuál es mejor?",
                "a": (
                    "Si tienes que elegir uno, elige whey. Tiene mejor perfil completo de aminoácidos "
                    "y mayor evidencia de resultados."
                ),
            },
            {
                "q": "¿Se pueden tomar los BCAA con el estómago vacío?",
                "a": (
                    "Sí, de hecho ese es uno de sus usos principales: antes del entreno en ayunas para "
                    "reducir el catabolismo muscular."
                ),
            },
            {
                "q": "¿Los BCAA tienen calorías?",
                "a": (
                    "Sí, aproximadamente 4 kcal/g, igual que cualquier proteína. No son un suplemento "
                    "libre de calorías."
                ),
            },
        ],
    },
    "Pre-Entreno": {
        "slug":     "pre-entreno",
        "display":  "Pre-Entreno",
        "icono":    "🔥",
        "icon_svg": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2L4.5 13.5H11L10 22L19.5 10.5H13L13 2z"/></svg>',
        "seo_title": "Mejor Precio Pre-Entreno España 2026",
        "seo_desc":  "Compara pre-entrenos en España ordenados por €/kg. "
                     "Precios actualizados de HSN, MyProtein, Nutritienda y Prozis.",
        "keywords":  "mejor precio pre-entreno España, comprar pre-workout barato, "
                     "pre-entreno oferta España, mejor pre-workout precio",
        "h1":    "Mejor Precio Pre-Entreno España",
        "intro": "Comparativa de pre-entrenos disponibles en tiendas españolas. "
                 "Ordenado por precio/kg para que compares con criterio.",
        "guia_titulo": "Cómo elegir un pre-entreno: ingredientes que funcionan y precio real por toma",
        "guia_texto": (
            "Los pre-entrenos son la categoría más heterogénea del mercado de suplementos. Pueden "
            "contener desde cafeína y beta-alanina hasta nootrópicos, adaptógenos o estimulantes de "
            "dudosa legalidad. Saber leer una etiqueta es clave antes de comprar.\n\n"
            "Ingredientes que funcionan de verdad: cafeína (150-300 mg por dosis), beta-alanina "
            "(3,2 g), citrulina malato (6-8 g), creatina monohidrato (3-5 g) y arginina. Estos son "
            "los compuestos con evidencia sólida para mejorar rendimiento, fuerza y resistencia.\n\n"
            "Red flags en la etiqueta: proprietary blends (mezclas propietarias sin desglosar "
            "cantidades), dosis de cafeína superiores a 400 mg, ingredientes como DMAA o DMHA "
            "(ilegales en Europa), o listas de 30 ingredientes sin especificar cuánto hay de cada uno.\n\n"
            "Cómo comparar por precio/kg: los pre-entrenos varían mucho en dosis por servicio (de "
            "8 g a 25 g). Un producto a 40 €/kg con 20 g por servicio te da 50 tomas. Otro a 30 €/kg "
            "con 10 g por servicio te da 100 tomas pero con la mitad de activos. Fíjate siempre en el "
            "precio por toma y los miligramos de ingredientes activos.\n\n"
            "Tolerancia y ciclado: la cafeína genera tolerancia rápidamente. Si usas pre-entreno a "
            "diario, cada 6-8 semanas conviene hacer una pausa de 1-2 semanas para resetear la "
            "sensibilidad. Evita tomarlo después de las 17:00 si eres sensible a la cafeína."
        ),
        "como_comparamos": (
            "Comparamos pre-entrenos de HSN, MyProtein, Nutritienda y Prozis ordenados por precio/kg. "
            "Ten en cuenta que los pre-entrenos varían mucho en composición: compara ingredientes y dosis "
            "además del precio para tomar la mejor decisión."
        ),
        "faq": [
            {
                "q": "¿El hormigueo que produce la beta-alanina es normal?",
                "a": (
                    "Sí, es una parestesia inofensiva. Se reduce tomando la dosis con comida o "
                    "dividiendo la toma en dos veces."
                ),
            },
            {
                "q": "¿Puedo tomar pre-entreno todos los días?",
                "a": (
                    "No es recomendable por la tolerancia a la cafeína. Mejor reservarlo para sesiones "
                    "exigentes y hacer pausas periódicas."
                ),
            },
            {
                "q": "¿Son seguros los pre-entrenos?",
                "a": (
                    "Los que tienen ingredientes bien dosificados y etiquetado transparente, sí. "
                    "Evita marcas sin información clara de composición o con estimulantes no declarados."
                ),
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
    "amix-pro":                 "Amix Pro",
    "bulk":                     "Bulk",
    "big":                      "Big",
    "mega-plus":                "Mega Plus",
    "dedicated-nutrition":      "Dedicated Nutrition",
    "dmi-innovative-nutrition": "DMI Innovative Nutrition",
    "biotech-usa":              "BioTechUSA",
    "biotechusa":               "BioTechUSA",
    "life-pro-nutrition":       "Life Pro Nutrition",
    "crown-sport-nutrition":    "Crown Sport Nutrition",
    "perfect-sports":           "Perfect Sports",
    # Marcas detectadas con descripción errónea como marca
    "best-protein":             "Best Protein",
    "amazin-foods":             "Amazin' Foods",
    "battery-nutrition":        "Battery Nutrition",
    "peak":                     "Peak",
    "nocco":                    "Nocco",
    "purasana":                 "Purasana",
    "muscletech":               "MuscleTech",
    "starlabs-nutrition":       "Starlabs Nutrition",
    "yamamoto-nutrition":       "Yamamoto Nutrition",
    "finisher":                 "Finisher",
    "cellucor":                 "Cellucor",
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

    # Unificar variantes conocidas y corregir pseudomarcas (descripción scrapeada como marca)
    NORMALIZACIONES = {
        "Nutrend": "NUTREND",
        # Nutritienda: descripción del producto usada como marca
        "Ramificados":                   "Best Protein",
        "Aminoácidos":                   "Amazin' Foods",
        "Aminoácidos ramificados":        "Amazin' Foods",
        "Glutamina + BCAAs":             "226ers",
        "Rendimiento Deportivo":         "Battery Nutrition",
        "Arginina Alfa-cetoglutarato":   "Peak",
        "Rico en BCAA y cafeína":        "Nocco",
        "Calidad Premium":               "Battery Nutrition",
        "Proteína Premium":              "Cellucor",
        "Whey Premium":                  "Purasana",
        "Orgánica":                      "Purasana",
        "Proteína Aislada Premium":      "MuscleTech",
        "¡Ultra pura!":                  "Starlabs Nutrition",
        "¡Eficacia y rendimiento!":      "Amazin' Foods",
        "¡Fórmula pre-entrenamiento!":   "Amix Pro",
        "Proteína sin gluten":           "BioTechUSA",
        "Proteína":                      "Yamamoto Nutrition",
        "Proteína Refrescante":          "BioTechUSA",
        "Proteína de suero enriquecida": "Finisher",
    }

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
    """
    Carga el JSON más reciente de la carpeta datasets/ que tenga datos
    válidos de múltiples tiendas.

    Un dataset se considera parcial (y se descarta) si:
    - Tiene menos de 150 productos, O
    - Solo contiene productos de una única tienda

    Esto evita que un scraping fallido (donde solo MyProtein o solo una
    tienda funcionó) sobreescriba los datos de todas las tiendas.
    """
    patron = os.path.join(DATASETS_DIR, "suplementos_*.json")
    ficheros = sorted(glob.glob(patron), reverse=True)

    if not ficheros:
        raise FileNotFoundError(
            f"No se encontró ningún fichero JSON en '{DATASETS_DIR}/'. "
            "Ejecuta primero python scraper.py"
        )

    for fichero in ficheros:
        with open(fichero, encoding="utf-8") as f:
            data = json.load(f)

        tiendas = {p.get("tienda") for p in data if p.get("tienda")}
        n_productos = len(data)

        if n_productos < 150 or len(tiendas) < 2:
            print(f"⚠️  Ignorando dataset parcial: {fichero} "
                  f"({n_productos} productos, tiendas: {tiendas})")
            continue

        print(f"📂 Cargando dataset: {fichero}")
        print(f"   → {n_productos} productos cargados ({len(tiendas)} tiendas)")
        return data, fichero

    raise FileNotFoundError(
        "Todos los datasets son parciales (< 150 productos o solo 1 tienda). "
        "Ejecuta python scraper.py con los scrapers funcionando correctamente."
    )


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
            "imagen_url":          g.get("imagen_url"),
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


def guardar_price_history(productos_web: list[dict]):
    """Añade los precios del scraping actual a data/price_history.json.

    Cada entrada tiene: producto_id, fecha, precio, tienda.
    Si el archivo ya existe, se conservan las entradas anteriores.
    No se duplican entradas con el mismo (producto_id, fecha, tienda).
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "price_history.json")

    # Cargar historial existente
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            historial = json.load(f)
    else:
        historial = []

    # Índice de entradas ya existentes para evitar duplicados
    existentes = {
        (e["producto_id"], e["fecha"], e["tienda"])
        for e in historial
    }

    nuevas = 0
    for producto in productos_web:
        producto_id = producto["id"]
        for precio_info in producto.get("precios", []):
            clave = (producto_id, precio_info["fecha"], precio_info["tienda"])
            if clave not in existentes:
                historial.append({
                    "producto_id": producto_id,
                    "fecha":       precio_info["fecha"],
                    "precio":      precio_info["precio_eur"],
                    "tienda":      precio_info["tienda"],
                })
                existentes.add(clave)
                nuevas += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

    print(f"📈 Historial: {path} ({nuevas} entradas nuevas, {len(historial)} total)")
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
        # Usar solo productos principales (excluye muestras, mal-categorizado, etc.)
        # para que el precio mínimo mostrado sea representativo
        prods_main = [p for p in prods_cat if not _excluir_producto(p)]
        precios_kg = [p["precio_por_kg_min"] for p in prods_main if p["precio_por_kg_min"]]
        categories.append({
            **cfg,
            "count":      len(prods_cat),
            "precio_min": min(precios_kg) if precios_kg else 0,
        })

    # Top 50 por precio/kg (paginados en home con JS)
    con_precio_kg = [p for p in productos_web if p["precio_por_kg_min"] is not None]
    # Excluir muestras/sachets del ranking home igual que en categorías
    con_precio_kg = [p for p in con_precio_kg if not _excluir_producto(p)]
    top_deals_raw = sorted(con_precio_kg, key=lambda p: p["precio_por_kg_min"])[:50]
    # Añadir img_src a cada top deal
    top_deals = []
    for p in top_deals_raw:
        p = dict(p)
        p["img_src"] = _img_local(p["id"], p["categoria"])
        top_deals.append(p)

    # Ahorro medio: diferencia % entre precio más caro y más barato entre tiendas
    savings = []
    for p in con_precio_kg:
        if len(p["precios"]) >= 2:
            precios_vals = sorted(pr["precio_eur"] for pr in p["precios"])
            if precios_vals[-1] > 0:
                savings.append((precios_vals[-1] - precios_vals[0]) / precios_vals[-1] * 100)
    ahorro_medio = round(sum(savings) / len(savings)) if savings else 0

    # Índice de búsqueda: todos los productos con €/kg para el buscador client-side
    all_search = []
    for p in sorted(con_precio_kg, key=lambda x: x["precio_por_kg_min"]):
        all_search.append({
            "nombre":      p["nombre_normalizado"],
            "marca":       p.get("marca", ""),
            "cat":         p["categoria"],
            "cat_display": p["categoria_display"],
            "peso_kg":     p.get("peso_kg"),
            "precio_kg":   p["precio_por_kg_min"],
            "tiendas": [
                {
                    "tienda":           pr["tienda"],
                    "precio":           pr["precio_eur"],
                    "url":              pr["url_afiliado"],
                    "oferta":           pr["en_oferta"],
                    "precio_original":  pr.get("precio_original"),
                }
                for pr in sorted(p["precios"], key=lambda x: x["precio_eur"])
            ],
        })

    ctx = {
        **contexto_base(last_updated),
        "total_productos":   len(productos_web),
        "total_tiendas":     len(tiendas),
        "tiendas_lista":     sorted(tiendas),
        "categories":        categories,
        "top_deals":         top_deals,
        "ahorro_medio":      ahorro_medio,
        "all_products_json": json.dumps(all_search, ensure_ascii=False),
    }

    html = template.render(**ctx)
    path = os.path.join(DOCS_DIR, "index.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Generado: {path}")


KEYWORDS_EXCLUIR = [
    "bicarbonato", "maltodextrina", "dextrosa",
    "muestra", "sample", "sachet", "monodosis",
]

# Keywords que deben ir a "Otros productos" según la categoría
# (productos mal clasificados que distorsionan el ranking)
KEYWORDS_EXCLUIR_POR_CATEGORIA = {
    "proteina-whey": [
        "sustitut",          # cubre "sustituto" Y "sustitutivo" (ambas formas)
        "crema de arroz",
        "colágeno marino", "colageno", "collagen",
        "meal replacement",
        "arroz en polvo",
    ],
    "pre-entreno": [
        "mug cake",          # mezcla de repostería, no es pre-workout
        "bebida energetica", "energy drink",
        "isomaltulosa", "palatinosa", "palatinose",  # carbohidrato a granel
        "aceite mct",        # grasa, no pre-workout
    ],
}


def _excluir_producto(p: dict) -> bool:
    """Devuelve True si el producto debe ir a 'Otros productos'."""
    precio_kg = p.get("precio_por_kg_min")
    if not precio_kg or precio_kg == 0:
        return True
    # Excluir muestras/sachets por peso < 150 g (distorsionan el €/kg)
    peso = p.get("peso_kg")
    if peso and peso < 0.15:
        return True
    nombre_lower = p.get("nombre_normalizado", "").lower()
    if any(kw in nombre_lower for kw in KEYWORDS_EXCLUIR):
        return True
    # Exclusiones específicas por categoría
    cat = p.get("categoria", "")
    cat_kws = KEYWORDS_EXCLUIR_POR_CATEGORIA.get(cat, [])
    return any(kw in nombre_lower for kw in cat_kws)


IMG_PRODUCTOS_DIR = os.path.join(DOCS_DIR, "img", "productos")

def _img_local(producto_id: str, categoria: str) -> str:
    """Devuelve la ruta web de la imagen local, o el placeholder SVG de categoría."""
    webp = os.path.join(IMG_PRODUCTOS_DIR, f"{producto_id}.webp")
    if os.path.exists(webp):
        return f"/img/productos/{producto_id}.webp"
    return f"/img/productos/placeholder-{categoria}.svg"


def _tipo_proteina(nombre: str) -> str:
    """Detecta tipo de whey por keywords en el nombre."""
    n = nombre.lower()
    if any(k in n for k in ("hidroliz", "hydrolyse", "hydrolys", "hidro", "hydro")):
        return "Hidrolizada"
    if any(k in n for k in ("isolat", "aislad")):
        return "Isolate"
    if any(k in n for k in ("concentr",)):
        return "Concentrada"
    return "Otra"


def generar_categoria(env, cat_raw: str, cfg: dict, productos_web: list[dict], last_updated: str):
    """Genera docs/{slug}/index.html para una categoría."""
    template = env.get_template("category.html")

    prods_cat = [p for p in productos_web if p["categoria"] == cfg["slug"]]

    # Separar tabla principal de "Otros productos"
    prods_principales = [p for p in prods_cat if not _excluir_producto(p)]
    prods_otros       = [p for p in prods_cat if _excluir_producto(p)]

    # Añadir tipo_proteina a whey y ruta de imagen local
    for p in prods_principales:
        p["img_src"] = _img_local(p["id"], cfg["slug"])
        if cfg["slug"] == "proteina-whey":
            p["tipo_proteina"] = _tipo_proteina(p["nombre_normalizado"])

    # Marcas únicas ordenadas
    marcas = sorted(set(p["marca"] for p in prods_principales if p.get("marca")))

    # Rango €/kg
    precios_kg = [p["precio_por_kg_min"] for p in prods_principales if p.get("precio_por_kg_min")]
    precio_kg_min = round(min(precios_kg), 1) if precios_kg else 0
    precio_kg_max = round(max(precios_kg), 1) if precios_kg else 999

    # Ya vienen ordenados por precio_por_kg desde convertir_a_schema_web
    tiendas = sorted(set(
        pr["tienda"]
        for p in prods_cat
        for pr in p["precios"]
    ))

    ctx = {
        **contexto_base(last_updated),
        "active_slug":     cfg["slug"],
        "cat":             cfg,
        "products":        prods_principales,
        "products_otros":  prods_otros,
        "tiendas":         tiendas,
        "marcas":          marcas,
        "precio_kg_min":   precio_kg_min,
        "precio_kg_max":   precio_kg_max,
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

# ============================================================
# PÁGINAS LEGALES Y SOBRE NOSOTROS
# ============================================================

PAGINAS_LEGALES = [
    {
        "slug":          "aviso-legal",
        "title":         "Aviso Legal",
        "meta_desc":     "Aviso legal de StackFit, comparador de precios de suplementos fitness en España.",
        "sitemap_priority": "0.3",
        "updated":       "2026-04-13",
        "content": """
<h2>Titular del sitio web</h2>
<p>En cumplimiento de la Ley 34/2002 de Servicios de la Sociedad de la Información y del Comercio Electrónico (LSSI-CE), se informa que el presente sitio web <strong>stackfit.es</strong> es titularidad de:</p>
<ul>
  <li><strong>Nombre:</strong> Javier Ortigosa</li>
  <li><strong>Email de contacto:</strong> <a href="mailto:javiortigosabarroso@gmail.com">javiortigosabarroso@gmail.com</a></li>
  <li><strong>Web:</strong> https://stackfit.es</li>
</ul>

<h2>Objeto del sitio</h2>
<p>StackFit es un comparador de precios de suplementos deportivos (proteína whey, creatina, BCAA y pre-entreno) disponibles en el mercado español. La finalidad del sitio es facilitar al usuario la comparación de precios entre distintas tiendas online, normalizando el coste por kilogramo para que la comparación sea justa independientemente del formato del producto.</p>
<p>StackFit no es una tienda online, no vende productos ni interviene en los procesos de compra. Las transacciones se realizan directamente entre el usuario y la tienda correspondiente.</p>

<h2>Propiedad intelectual</h2>
<p>El diseño, código fuente, textos editoriales y estructura del sitio son propiedad de Javier Ortigosa. Los nombres de productos, marcas y logotipos que aparecen en el comparador son propiedad de sus respectivos titulares (HSN, MyProtein, Nutritienda, Prozis, etc.) y se muestran únicamente con fines informativos y comparativos.</p>
<p>Los precios, nombres de producto y demás datos comerciales son extraídos de fuentes públicas y pueden estar sujetos a derechos de sus respectivos propietarios.</p>

<h2>Exclusión de responsabilidad</h2>
<p>Los precios mostrados en StackFit se obtienen de forma automática y pueden no reflejar en todo momento el precio real de venta en cada tienda. Los precios pueden variar sin previo aviso por parte de las tiendas. StackFit no garantiza la exactitud de los precios ni la disponibilidad de los productos.</p>
<p>El usuario debe verificar el precio final en la página de la tienda antes de realizar cualquier compra. StackFit no asume responsabilidad por las transacciones realizadas en sitios web de terceros.</p>

<h2>Modelo de ingresos</h2>
<p>StackFit participa en programas de afiliación (Awin, entre otros). Algunos de los enlaces mostrados son enlaces de afiliado: si el usuario realiza una compra a través de ellos, StackFit puede recibir una pequeña comisión sin coste adicional para el comprador. Esto no influye en la ordenación de los resultados, que se basa exclusivamente en el precio por kilogramo.</p>

<h2>Legislación aplicable</h2>
<p>Este aviso legal se rige por la legislación española. Cualquier controversia derivada del uso del sitio web se someterá a los juzgados y tribunales competentes conforme a la normativa española aplicable.</p>
""",
    },
    {
        "slug":          "privacidad",
        "title":         "Política de Privacidad",
        "meta_desc":     "Política de privacidad de StackFit. Información sobre el tratamiento de datos y cookies.",
        "sitemap_priority": "0.3",
        "updated":       "2026-04-13",
        "content": """
<h2>Responsable del tratamiento</h2>
<p>El responsable del tratamiento de los datos es <strong>Javier Ortigosa</strong>, contactable en <a href="mailto:javiortigosabarroso@gmail.com">javiortigosabarroso@gmail.com</a>.</p>

<h2>Datos que se recogen</h2>
<p>StackFit <strong>no recoge ningún dato personal</strong> de sus usuarios de forma directa. El sitio no dispone de formularios de registro, áreas privadas, ni funcionalidades que requieran identificación del usuario.</p>
<p>Sin embargo, al navegar por StackFit pueden generarse registros técnicos en el servidor (dirección IP, navegador, páginas visitadas, hora de acceso) de forma anónima y agregada, gestionados por GitHub Pages como proveedor de alojamiento.</p>

<h2>Cookies y tecnologías de seguimiento</h2>
<p>StackFit <strong>no utiliza cookies propias</strong> de ningún tipo (analíticas, de marketing ni funcionales).</p>
<p>No obstante, los servicios de terceros vinculados al sitio pueden establecer sus propias cookies:</p>
<ul>
  <li><strong>Google Search Console:</strong> utilizado para monitorizar la presencia del sitio en resultados de búsqueda. Puede implicar el procesamiento de datos de navegación por parte de Google. Consulta la <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">política de privacidad de Google</a>.</li>
  <li><strong>Awin (programa de afiliados):</strong> los enlaces de afiliado pueden contener identificadores de seguimiento que permiten a Awin registrar si una compra se ha originado desde StackFit. Consulta la <a href="https://www.awin.com/es/privacidad" target="_blank" rel="noopener">política de privacidad de Awin</a>.</li>
  <li><strong>Tiendas vinculadas</strong> (HSN, MyProtein, Nutritienda, Prozis): al hacer clic en un enlace y acceder a su web, quedarás sujeto a sus propias políticas de privacidad y cookies.</li>
</ul>

<h2>Base legal del tratamiento</h2>
<p>El funcionamiento del sitio se basa en el interés legítimo del titular para ofrecer un servicio de información y comparación de precios (art. 6.1.f del RGPD). No se realiza ningún tratamiento de datos personales que requiera consentimiento explícito.</p>

<h2>Derechos de los usuarios</h2>
<p>En la medida en que pudiera existir algún tratamiento de datos personales, los usuarios tienen derecho a ejercer los derechos de acceso, rectificación, supresión, oposición, limitación y portabilidad, contactando a <a href="mailto:javiortigosabarroso@gmail.com">javiortigosabarroso@gmail.com</a>. También pueden presentar una reclamación ante la Agencia Española de Protección de Datos (<a href="https://www.aepd.es" target="_blank" rel="noopener">aepd.es</a>).</p>

<h2>Cambios en esta política</h2>
<p>Esta política puede actualizarse para reflejar cambios en el funcionamiento del sitio o en la normativa aplicable. Se indicará la fecha de última actualización al inicio de esta página.</p>
""",
    },
    {
        "slug":          "sobre-nosotros",
        "title":         "Sobre Nosotros",
        "meta_desc":     "Qué es StackFit, cómo funciona y quién hay detrás. Un comparador honesto de suplementos fitness en España.",
        "sitemap_priority": "0.5",
        "updated":       None,
        "content": """
<h2>Qué es StackFit</h2>
<p>StackFit es un comparador de precios de suplementos deportivos en España. Compara proteína whey, creatina, BCAA y pre-entreno entre HSN, MyProtein, Nutritienda y Prozis, ordenando los resultados por precio por kilogramo para que la comparación sea justa independientemente del tamaño del bote.</p>
<p>La idea es simple: que no tengas que abrir cuatro pestañas distintas y hacer cálculos mentales para saber qué bote de proteína sale más barato por gramo.</p>

<h2>Cómo funciona</h2>
<p>Varios días a la semana, unos scrapers automáticos recorren las páginas de cada tienda, extraen los precios y los normalizan a euros por kilogramo. Los resultados se publican en el sitio de forma automática, sin intervención manual en los precios.</p>
<p>El proceso completo — desde el scraping hasta la web publicada — está construido en Python y corre en local. No hay base de datos, no hay servidor: el resultado es HTML estático servido desde GitHub Pages.</p>

<h2>Quién lo hace</h2>
<p>Soy Javier, estudiante de Ingeniería Matemática y aficionado al fitness. Empecé este proyecto porque compraba suplementos con frecuencia y no encontraba una herramienta que comparara precios en el mercado español de forma honesta y normalizada por kilogramo. Así que la construí.</p>
<p>StackFit es un proyecto personal. No hay equipo, no hay inversión, no hay oficina. Hay código, tiempo libre y ganas de que la herramienta sea útil.</p>

<h2>Modelo de negocio</h2>
<p>Algunos de los enlaces del sitio son enlaces de afiliado: si compras a través de ellos, recibo una pequeña comisión sin que te cueste nada extra. Esto es lo que permite mantener el proyecto activo. La ordenación de los resultados es siempre por precio por kilogramo, no por comisión.</p>
<p>Cualquier pregunta o sugerencia: <a href="mailto:javiortigosabarroso@gmail.com">javiortigosabarroso@gmail.com</a>.</p>
""",
    },
]


def generar_pagina_legal(env, pagina: dict, last_updated: str):
    """Genera docs/{slug}/index.html para una página legal o informativa."""
    template = env.get_template("legal.html")
    ctx = {
        **contexto_base(last_updated),
        "page_title":    pagina["title"],
        "page_meta_desc": pagina["meta_desc"],
        "page_slug":     pagina["slug"],
        "page_content":  pagina["content"],
        "page_updated":  pagina.get("updated"),
    }
    html = template.render(**ctx)
    outdir = os.path.join(DOCS_DIR, pagina["slug"])
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Generado: {path}")


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
    for pagina in PAGINAS_LEGALES:
        urls.append({
            "loc":        f"{SITE_URL}/{pagina['slug']}/",
            "priority":   pagina["sitemap_priority"],
            "changefreq": "monthly",
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

    # 3. Guardar products.json y price_history.json
    print()
    guardar_products_json(productos_web)
    guardar_price_history(productos_web)

    # 4. Generar HTML
    print("\n🏗️  Generando HTML...")
    env = setup_jinja()

    generar_home(env, productos_web, last_updated)

    for cat_raw, cfg in CATEGORIA_CONFIG.items():
        generar_categoria(env, cat_raw, cfg, productos_web, last_updated)

    # 5. Páginas legales y sobre nosotros
    for pagina in PAGINAS_LEGALES:
        generar_pagina_legal(env, pagina, last_updated)

    # 6. Sitemap, robots, .nojekyll
    print("\n📋 Generando ficheros auxiliares...")
    generar_sitemap(last_updated)
    generar_robots()
    generar_nojekyll()

    duracion = (datetime.now() - inicio).total_seconds()
    total_paginas = 1 + len(CATEGORIA_CONFIG) + len(PAGINAS_LEGALES)

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
