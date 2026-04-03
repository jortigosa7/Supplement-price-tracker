"""
Corrige el campo 'marca' en data/products.json para productos con marca 'Desconocida':
  1. Nutritienda: extrae la marca del segmento de URL /es/{MARCA}/{producto}
  2. MyProtein:   asigna 'MyProtein' si alguna URL es de myprotein.com
  3. HSN:         asigna 'HSN' si todas las URLs conocidas son de hsnstore.com
  4. Prozis:      asigna 'Prozis' si alguna URL es de prozis.com y no se resolvió antes
"""

import json
import re

# Mapa slug → nombre de marca legible para Nutritienda
SLUG_MARCA = {
    "fire-nutrition":         "Fire Nutrition",
    "beverly-nutrition":      "Beverly Nutrition",
    "amix-nutrition":         "Amix Nutrition",
    "amix-performance":       "Amix",
    "bulk":                   "Bulk",
    "big":                    "Big",
    "mega-plus":              "Mega Plus",
    "dedicated-nutrition":    "Dedicated Nutrition",
    "dmi-innovative-nutrition": "DMI Innovative Nutrition",
    "biotech-usa":            "BioTechUSA",
    "life-pro-nutrition":     "Life Pro Nutrition",
    "crown-sport-nutrition":  "Crown Sport Nutrition",
    "perfect-sports":         "Perfect Sports",
}


def slug_to_marca(slug):
    """Convierte un slug de Nutritienda a nombre de marca."""
    if slug in SLUG_MARCA:
        return SLUG_MARCA[slug]
    # Fallback: Title Case reemplazando guiones por espacios
    return slug.replace("-", " ").title()


def marca_desde_nutritienda(urls):
    for url in urls:
        if "nutritienda.com" in url:
            parts = url.rstrip("/").split("/")
            # https://www.nutritienda.com/es/{MARCA}/{producto}
            if len(parts) >= 5 and parts[4] not in ("es", "www", ""):
                return slug_to_marca(parts[4])
    return None


def marca_desde_myprotein(urls):
    for url in urls:
        if "myprotein." in url:
            return "MyProtein"
    return None


def marca_desde_hsn(urls):
    for url in urls:
        if "hsnstore.com" in url:
            return "HSN"
    return None


def marca_desde_prozis(urls):
    for url in urls:
        if "prozis.com" in url:
            return "Prozis"
    return None


INPUT_FILE = "data/products.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

stats = {"nutritienda": 0, "myprotein": 0, "hsn": 0, "prozis": 0, "sin_cambio": 0}

for product in data["products"]:
    if product.get("marca") != "Desconocida":
        continue

    urls = [pr.get("url_afiliado", "") for pr in product.get("precios", [])]

    # Prioridad: Nutritienda (más info) > MyProtein > HSN > Prozis
    nueva_marca = (
        marca_desde_nutritienda(urls)
        or marca_desde_myprotein(urls)
        or marca_desde_hsn(urls)
        or marca_desde_prozis(urls)
    )

    if nueva_marca:
        fuente = (
            "nutritienda" if marca_desde_nutritienda(urls)
            else "myprotein" if marca_desde_myprotein(urls)
            else "hsn" if marca_desde_hsn(urls)
            else "prozis"
        )
        product["marca"] = nueva_marca
        stats[fuente] += 1
    else:
        stats["sin_cambio"] += 1

with open(INPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

total = sum(v for k, v in stats.items() if k != "sin_cambio")
print(f"Marcas corregidas: {total}")
print(f"  Nutritienda (slug en URL): {stats['nutritienda']}")
print(f"  MyProtein   (URL):         {stats['myprotein']}")
print(f"  HSN         (URL):         {stats['hsn']}")
print(f"  Prozis      (URL):         {stats['prozis']}")
print(f"  Sin resolver:              {stats['sin_cambio']}")
