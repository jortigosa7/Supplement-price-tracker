# -*- coding: utf-8 -*-
"""Scrape HSN, merge into today's dataset, rebuild site."""
import json
import datetime
import sys
import os

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

from scrapers.hsn import scrape as scrape_hsn
from limpieza import limpiar_precio, extraer_peso_kg, extraer_marca

# ── 1. Scrape HSN ────────────────────────────────────────────────────────────
hsn_prods = scrape_hsn()
print(f"HSN raw: {len(hsn_prods)}")

# ── 2. Limpiar manualmente (misma lógica que limpiar_dataset) ────────────────
ENRICHMENT_FIELDS = [
    "store_rating", "store_rating_count", "store_rating_url",
    "flavors_available", "protein_per_serving_g", "serving_size_g",
    "servings_per_container", "sweetener_free", "vegan",
]

df = pd.DataFrame(hsn_prods)
df["precio_eur"] = df["precio"].apply(limpiar_precio)
df["peso_kg"] = df["nombre"].apply(extraer_peso_kg)
df["precio_por_kg"] = df.apply(
    lambda r: round(r["precio_eur"] / r["peso_kg"], 2)
    if pd.notna(r["precio_eur"]) and pd.notna(r["peso_kg"]) and r["peso_kg"] > 0
    else None,
    axis=1,
)
for col in ["nombre", "categoria", "tienda"]:
    if col in df.columns:
        df[col] = df[col].astype(str).str.strip()
if "marca" not in df.columns or df["marca"].isna().all():
    df["marca"] = df["nombre"].apply(extraer_marca)
df = df.dropna(subset=["precio_eur"])
df = df.drop_duplicates(subset=["nombre", "tienda"], keep="first")
print(f"HSN limpio: {len(df)}")

# Re-attach enrichment fields (limpiar_dataset drops unknown cols, re-add from raw)
enrich_by_url = {}
for p in hsn_prods:
    url = p.get("url", "")
    if url:
        enrich_by_url[url] = {k: p[k] for k in ENRICHMENT_FIELDS if p.get(k) is not None}

hsn_records = df.to_dict("records")
for r in hsn_records:
    r.update(enrich_by_url.get(r.get("url", ""), {}))

# ── 3. Merge with existing dataset ──────────────────────────────────────────
with open("datasets/suplementos_20260417.json", encoding="utf-8") as f:
    existing = json.load(f)

sin_hsn = [p for p in existing if p.get("tienda") != "HSN"]
merged = sin_hsn + hsn_records
tiendas = {p.get("tienda") for p in merged}
print(f"Fusionado: {len(merged)} productos, tiendas: {tiendas}")

# ── 4. Save as new dataset ───────────────────────────────────────────────────
ts = datetime.date.today().strftime("%Y%m%d")
out = f"datasets/suplementos_{ts}.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)
print(f"Guardado: {out}")

# ── 5. Rebuild site ──────────────────────────────────────────────────────────
print("\nEjecutando build.py...")
import build  # noqa: E402
import importlib
importlib.reload(build)
build.main()
