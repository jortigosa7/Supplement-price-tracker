"""
añadir_afiliados.py
====================
Actualiza data/products.json con links de afiliado en el campo url_afiliado.

Programas implementados:
  - HSN         → base64 encoding (ID: JORTIGOSA), aprobado
  - Amazon      → tag suplemento0f1-21, activo
  - Awin (MyProtein, Prozis, Nutritienda) → requiere variables de entorno (pendiente aprobación)

Ejecutar desde la raíz del proyecto:
  python añadir_afiliados.py
"""

import base64
import json
import os
import warnings
from urllib.parse import quote

INPUT_FILE  = "data/products.json"
OUTPUT_FILE = "data/products.json"

# ── HSN ────────────────────────────────────────────────────────────────────────
HSN_AFFID = "JORTIGOSA"

def hsn_affiliate_link(product_url: str) -> str:
    raw = f"product||||{HSN_AFFID}||{product_url}"
    encoded = base64.b64encode(raw.encode()).decode()
    return f"https://www.hsnstore.com/affiliate/click/index?linkid={encoded}"

# ── Amazon ─────────────────────────────────────────────────────────────────────
AMAZON_TAG = "suplemento0f1-21"

def amazon_affiliate_link(url: str) -> str:
    if f"tag={AMAZON_TAG}" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}tag={AMAZON_TAG}"

# ── Awin (pendiente de aprobación) ─────────────────────────────────────────────
AWIN_AFFID = os.environ.get("AWIN_AFFID")
AWIN_MERCHANTS = {
    "myprotein":   os.environ.get("AWIN_MID_MYPROTEIN"),
    "prozis":      os.environ.get("AWIN_MID_PROZIS"),
    "nutritienda": os.environ.get("AWIN_MID_NUTRITIENDA"),
}

def awin_affiliate_link(destination_url: str, awinmid: str) -> str:
    encoded = quote(destination_url, safe="")
    return (
        f"https://www.awin1.com/cread.php"
        f"?awinmid={awinmid}&awinaffid={AWIN_AFFID}&ued={encoded}"
    )

# ── Main ───────────────────────────────────────────────────────────────────────
with open(INPUT_FILE, encoding="utf-8") as f:
    data = json.load(f)

hsn_count     = 0
amazon_count  = 0
awin_count    = 0
hsn_examples  = []

for product in data.get("products", []):
    for precio in product.get("precios", []):
        tienda  = precio.get("tienda", "")
        url_raw = precio.get("url_afiliado", "")
        if not url_raw:
            continue

        tienda_lower = tienda.lower()

        # HSN ──────────────────────────────────────────────────────────────────
        if tienda_lower == "hsn":
            # Solo aplicar si no es ya un link de afiliado HSN
            if "affiliate/click" not in url_raw:
                nueva = hsn_affiliate_link(url_raw)
                precio["url_afiliado"] = nueva
                hsn_count += 1
                if len(hsn_examples) < 3:
                    hsn_examples.append((url_raw, nueva))

        # Amazon ───────────────────────────────────────────────────────────────
        elif "amazon.es" in url_raw:
            nueva = amazon_affiliate_link(url_raw)
            if nueva != url_raw:
                precio["url_afiliado"] = nueva
                amazon_count += 1

        # Awin (MyProtein, Prozis, Nutritienda) ────────────────────────────────
        elif tienda_lower in AWIN_MERCHANTS:
            if not AWIN_AFFID:
                continue
            awinmid = AWIN_MERCHANTS[tienda_lower]
            if not awinmid:
                warnings.warn(
                    f"AWIN_MID para '{tienda}' no definido — se omite",
                    stacklevel=2,
                )
                continue
            if "awin1.com" not in url_raw:
                precio["url_afiliado"] = awin_affiliate_link(url_raw, awinmid)
                awin_count += 1

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# ── Resumen ────────────────────────────────────────────────────────────────────
print(f"\nAfiliados añadidos:")
print(f"   HSN        -> {hsn_count} productos (ID: {HSN_AFFID})")
print(f"   Amazon     -> {amazon_count} productos (tag: {AMAZON_TAG})")
print(f"   Awin       -> {awin_count} productos")
print(f"\n   Archivo guardado: {OUTPUT_FILE}")

if hsn_examples:
    print(f"\nEjemplos de links HSN generados ({len(hsn_examples)}):")
    for i, (original, afiliado) in enumerate(hsn_examples, 1):
        print(f"\n   [{i}] Original : {original}")
        print(f"       Afiliado : {afiliado}")
