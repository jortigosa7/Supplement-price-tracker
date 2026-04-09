import json
import os
import warnings
from urllib.parse import quote

INPUT_FILE = "data/productos.json"
OUTPUT_FILE = "data/productos.json"

AWIN_AFFID = os.environ.get("AWIN_AFFID")

MERCHANT_ENV_VARS = {
    "myprotein":   "AWIN_MID_MYPROTEIN",
    "prozis":      "AWIN_MID_PROZIS",
    "nutritienda": "AWIN_MID_NUTRITIENDA",
}


def build_awin_url(destination_url: str, awinmid: str, awinaffid: str) -> str:
    encoded = quote(destination_url, safe="")
    return (
        f"https://www.awin1.com/cread.php"
        f"?awinmid={awinmid}&awinaffid={awinaffid}&ued={encoded}"
    )


def get_awinmid(tienda: str) -> str | None:
    env_var = MERCHANT_ENV_VARS.get(tienda.lower())
    if env_var is None:
        return None
    value = os.environ.get(env_var)
    if not value:
        warnings.warn(
            f"Variable de entorno '{env_var}' no definida — se omite tienda '{tienda}'",
            stacklevel=2,
        )
        return None
    return value


if not AWIN_AFFID:
    raise EnvironmentError("La variable de entorno 'AWIN_AFFID' no está definida.")

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

updated = 0

for product in data.get("products", []):
    for precio in product.get("precios", []):
        tienda = precio.get("tienda", "")
        awinmid = get_awinmid(tienda)
        if awinmid is None:
            continue
        url_original = precio.get("url_afiliado", "")
        if not url_original:
            continue
        precio["url_afiliado"] = build_awin_url(url_original, awinmid, AWIN_AFFID)
        updated += 1

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Listo — {updated} URLs actualizadas con enlaces de afiliado Awin.")
print(f"Archivo guardado en: {OUTPUT_FILE}")
