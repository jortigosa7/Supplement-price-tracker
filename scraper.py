"""
scraper.py — Orquestador de scrapers de suplementos fitness
============================================================

Ejecuta todos los scrapers activos, limpia los datos y guarda
el dataset plano en datasets/suplementos_YYYYMMDD.json

Uso:
    python scraper.py                  # scraping normal
    python scraper.py --debug-hsn        # guarda HTML de HSN para inspeccionar selectores
    python scraper.py --debug-prozis     # guarda HTML de Prozis
    python scraper.py --debug-myprotein  # guarda HTML de MyProtein

Salida:
    datasets/suplementos_YYYYMMDD.csv
    datasets/suplementos_YYYYMMDD.json
"""

import sys
import os
import json
import glob

# Forzar UTF-8 en stdout (necesario en Windows con cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time
from datetime import datetime
import pandas as pd

from limpieza import limpiar_dataset
from scrapers import nutritienda, hsn, prozis, myprotein

OUTPUT_DIR = "datasets"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def guardar_dataset(df: pd.DataFrame) -> tuple[str, str]:
    """Guarda el DataFrame como CSV y JSON con timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d")

    columnas = [
        "nombre", "marca", "categoria", "precio_eur", "peso_kg",
        "precio_por_kg", "tienda", "url", "imagen_url", "fecha_scraping",
        # Campos de enriquecimiento (pueden estar null si el scraper no los extrajo)
        "protein_per_serving_g", "serving_size_g", "servings_per_container",
        "sweetener_free", "vegan", "flavors_available",
        "store_rating", "store_rating_count", "store_rating_url",
    ]
    cols_ok = [c for c in columnas if c in df.columns]
    df_out  = df[cols_ok].copy()

    if "precio_por_kg" in df_out.columns:
        df_out = df_out.sort_values(["categoria", "precio_por_kg"], na_position="last")

    csv_path  = os.path.join(OUTPUT_DIR, f"suplementos_{timestamp}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"suplementos_{timestamp}.json")

    df_out.to_csv(csv_path,  index=False, encoding="utf-8-sig")
    df_out.to_json(json_path, orient="records", force_ascii=False, indent=2)

    return csv_path, json_path


def mostrar_resumen(df: pd.DataFrame):
    print(f"\n{'='*50}")
    print("  RESUMEN")
    print(f"{'='*50}")
    print(f"  Total productos : {len(df)}")
    if "tienda" in df.columns:
        for tienda, n in df["tienda"].value_counts().items():
            print(f"    {tienda}: {n}")
    if "precio_eur" in df.columns:
        print(f"  Precio medio    : {df['precio_eur'].mean():.2f} EUR")
    if "precio_por_kg" in df.columns and df["precio_por_kg"].notna().any():
        mejor = df.loc[df["precio_por_kg"].idxmin()]
        print(f"  Mejor precio/kg : {mejor['nombre']} — {mejor['precio_por_kg']} EUR/kg ({mejor['tienda']})")


if __name__ == "__main__":
    debug_hsn        = "--debug-hsn"        in sys.argv
    debug_prozis     = "--debug-prozis"     in sys.argv
    debug_myprotein  = "--debug-myprotein"  in sys.argv

    print("\n" + "=" * 50)
    print("  SUPPLEMENT PRICE SCRAPER")
    print("=" * 50)
    inicio = time.time()

    todos = []

    # ── Nutritienda (requests + BS4, siempre activo) ──
    try:
        productos = nutritienda.scrape()
        todos.extend(productos)
        print(f"  Nutritienda: {len(productos)} productos")
    except Exception as e:
        print(f"  ERROR Nutritienda: {e}")

    # ── HSN (Playwright — activo cuando los selectores estén configurados) ──
    try:
        productos = hsn.scrape(debug=debug_hsn)
        todos.extend(productos)
        if productos:
            print(f"  HSN: {len(productos)} productos")
    except Exception as e:
        print(f"  ERROR HSN: {e}")

    # ── Prozis (requests + BS4 — extrae wsData JSON del HTML) ──────────────
    try:
        productos = prozis.scrape(debug=debug_prozis)
        todos.extend(productos)
        if productos:
            print(f"  Prozis: {len(productos)} productos")
    except Exception as e:
        print(f"  ERROR Prozis: {e}")

    # ── MyProtein (requests + BS4 — extrae JSON-LD del HTML) ────────────────
    try:
        productos = myprotein.scrape(debug=debug_myprotein)
        todos.extend(productos)
        if productos:
            print(f"  MyProtein: {len(productos)} productos")
    except Exception as e:
        print(f"  ERROR MyProtein: {e}")

    print(f"\n  Total scrapeados: {len(todos)}")

    if not todos:
        print("\n  Sin productos. Revisa la conexion o los selectores.")
        sys.exit(1)

    # ── Safeguard: verificar que no perdemos >20% vs el scrape anterior ──────
    prev_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "suplementos_*.json")), reverse=True)
    if prev_files:
        try:
            with open(prev_files[0], encoding="utf-8") as _f:
                prev_count = len(json.load(_f))
            if len(todos) < prev_count * 0.80:
                print(
                    f"\n⚠️  ABORTANDO: solo {len(todos)} productos scrapeados "
                    f"vs {prev_count} en el scrape anterior (< 80%). "
                    f"Revisa los scrapers antes de sobreescribir products.json."
                )
                sys.exit(1)
        except Exception as _e:
            print(f"  Aviso: no se pudo leer dataset anterior: {_e}")

    # Limpiar
    df = limpiar_dataset(todos)
    if df.empty:
        print("  Sin datos tras limpieza.")
        sys.exit(1)

    # Guardar
    csv_path, json_path = guardar_dataset(df)
    print(f"\n  Guardado: {json_path}")

    mostrar_resumen(df)

    duracion = time.time() - inicio
    print(f"\n  Tiempo total: {duracion:.1f}s")
    print(f"\n  SIGUIENTE: python build.py")
