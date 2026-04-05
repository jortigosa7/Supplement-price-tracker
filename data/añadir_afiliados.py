import json

# ── Configuración ──────────────────────────────────────────
AMAZON_TAG = "suplemento0f1-21"
INPUT_FILE  = "data/products.json"   # ajusta la ruta si es distinta
OUTPUT_FILE = "data/products.json"   # sobreescribe el mismo archivo
# ───────────────────────────────────────────────────────────

def añadir_tag_amazon(url: str) -> str:
    """Añade ?tag= o &tag= a una URL de Amazon si no lo tiene ya."""
    if "amazon.es" not in url:
        return url
    if f"tag={AMAZON_TAG}" in url:
        return url  # ya tiene el tag, no tocar
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}tag={AMAZON_TAG}"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    products = json.load(f)

amazon_count = 0

for product in products:
    for precio in product.get("precios", []):
        url_original = precio.get("url_afiliado", "")
        url_nueva = añadir_tag_amazon(url_original)
        if url_nueva != url_original:
            precio["url_afiliado"] = url_nueva
            amazon_count += 1

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(products, f, ensure_ascii=False, indent=2)

print(f"✅ Listo — {amazon_count} URLs de Amazon actualizadas con tag '{AMAZON_TAG}'")
print(f"   Archivo guardado en: {OUTPUT_FILE}")
