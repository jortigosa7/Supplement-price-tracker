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
        # Subtipo de proteína (whey, caseína, vegetal, huevo, secuencial, carne)
        "protein_subtype",
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

    # ── HSN (requests + BeautifulSoup) ──────────────────────────────────────
    try:
        productos_hsn = hsn.scrape(debug=debug_hsn)

        # Ancla de nombre por URL: si un producto salió sin peso en el nombre,
        # recuperar el nombre anterior (con peso) del último dataset para
        # mantener el ID estable ante fallos puntuales del scraper.
        if productos_hsn:
            from limpieza import extraer_peso_kg as _epk
            prev_jsons = sorted(glob.glob(os.path.join(OUTPUT_DIR, "suplementos_*.json")), reverse=True)
            url_to_prev_nombre: dict[str, str] = {}
            if prev_jsons:
                try:
                    with open(prev_jsons[0], encoding="utf-8") as _f:
                        prev_raw = json.load(_f)
                    for _p in prev_raw:
                        if _p.get("tienda") == "HSN" and _epk(_p.get("nombre", "")):
                            url_to_prev_nombre[_p.get("url", "")] = _p.get("nombre", "")
                except Exception:
                    pass
            restaurados = 0
            for prod in productos_hsn:
                if not _epk(prod.get("nombre", "")):
                    prev_nombre = url_to_prev_nombre.get(prod.get("url", ""))
                    if prev_nombre and _epk(prev_nombre):
                        prod["nombre"] = prev_nombre
                        prod.pop("_precio_sin_confirmar", None)  # peso ya estaba antes, no marcar
                        restaurados += 1
            if restaurados:
                print(f"  ⚠️  HSN: {restaurados} nombre(s) restaurado(s) desde dataset anterior (peso faltante)")

        todos.extend(productos_hsn)
        if productos_hsn:
            print(f"  HSN: {len(productos_hsn)} productos")
    except Exception as e:
        print(f"  ERROR HSN: {e}")

    # ── Prozis (Playwright — extrae wsData JSON del HTML) ───────────────────
    prev_prozis_cat_counts: dict[str, int] = {}
    productos_prozis: list[dict] = []
    try:
        if prev_data:
            for _p in prev_data:
                if _p.get("tienda") == "Prozis":
                    _cat = _p.get("categoria", "")
                    prev_prozis_cat_counts[_cat] = prev_prozis_cat_counts.get(_cat, 0) + 1

        productos_prozis = prozis.scrape(debug=debug_prozis, prev_cat_counts=prev_prozis_cat_counts)
        todos.extend(productos_prozis)
        if productos_prozis:
            print(f"  Prozis: {len(productos_prozis)} productos")
    except Exception as e:
        print(f"  ERROR Prozis: {e}")

    # Fallback por categoría Prozis: si alguna sigue por debajo del 60%, reponer del dataset previo
    if prev_data and prev_prozis_cat_counts and not debug_prozis:
        cat_counts_nuevo: dict[str, int] = {}
        for _p in productos_prozis:
            _cat = _p.get("categoria", "")
            cat_counts_nuevo[_cat] = cat_counts_nuevo.get(_cat, 0) + 1

        scrape_stats_path = os.path.join("data", "scrape_stats.json")
        try:
            with open(scrape_stats_path, encoding="utf-8") as _sf:
                scrape_stats = json.load(_sf)
        except Exception:
            scrape_stats = {}
        fallback_consec: dict[str, int] = scrape_stats.get("prozis_fallback_consecutivo", {})

        for cat_nombre, prev_count in prev_prozis_cat_counts.items():
            if prev_count == 0:
                continue
            nuevo_count = cat_counts_nuevo.get(cat_nombre, 0)
            if nuevo_count < prev_count * 0.60:
                # Reponer categoría del dataset anterior
                todos = [_p for _p in todos if not (
                    _p.get("tienda") == "Prozis" and _p.get("categoria") == cat_nombre
                )]
                prev_cat = [_p for _p in prev_data
                            if _p.get("tienda") == "Prozis" and _p.get("categoria") == cat_nombre]
                if prev_cat:
                    for _p in prev_cat:
                        if "precio" not in _p and "precio_eur" in _p and _p["precio_eur"] is not None:
                            _p["precio"] = str(_p["precio_eur"])
                        # NO se sobreescribe fecha_scraping: preservar la fecha real del dato
                    todos.extend(prev_cat)
                    fallback_consec[cat_nombre] = fallback_consec.get(cat_nombre, 0) + 1
                    print(
                        f"\n  ⚠️  Prozis/{cat_nombre}: {nuevo_count} productos "
                        f"(esperado ~{prev_count}) — fallback a {len(prev_cat)} productos anteriores "
                        f"(consecutivo: {fallback_consec[cat_nombre]})"
                    )
            else:
                fallback_consec[cat_nombre] = 0  # reset si la categoría volvió

        scrape_stats["prozis_fallback_consecutivo"] = fallback_consec
        os.makedirs("data", exist_ok=True)
        with open(scrape_stats_path, "w", encoding="utf-8") as _sf:
            json.dump(scrape_stats, _sf, ensure_ascii=False, indent=2)

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

        # ── Fallback por tienda: si un scraper devolvió 0, reutilizar datos anteriores ──
    prev_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "suplementos_*.json")), reverse=True)
    prev_data: list[dict] = []
    if prev_files:
        try:
            with open(prev_files[0], encoding="utf-8") as _f:
                prev_data = json.load(_f)
        except Exception as _e:
            print(f"  Aviso: no se pudo leer dataset anterior para fallback: {_e}")

    if prev_data:
        tiendas_nuevas = {p.get("tienda", "") for p in todos if p.get("tienda")}
        tiendas_prev   = {p.get("tienda", "") for p in prev_data if p.get("tienda")}
        tiendas_bloqueadas = tiendas_prev - tiendas_nuevas
        for tienda in sorted(tiendas_bloqueadas):
            fallback = [p for p in prev_data if p.get("tienda") == tienda]
            if not fallback:
                continue
            for p in fallback:
                if "precio" not in p and "precio_eur" in p and p["precio_eur"] is not None:
                    p["precio"] = str(p["precio_eur"])
                # NO se sobreescribe fecha_scraping: el dato es viejo, que se vea viejo en la web
            todos.extend(fallback)
            print(
                f"\n  ⚠️  {tienda}: 0 productos nuevos — "
                f"usando {len(fallback)} productos del dataset anterior como fallback"
            )

    # ── Safeguard: verificar que no perdemos >20% vs el scrape anterior ──────
    if prev_data:
        try:
            prev_count = len(prev_data)
            if len(todos) < prev_count * 0.80:
                print(
                    f"\n⚠️  ABORTANDO: solo {len(todos)} productos scrapeados "
                    f"vs {prev_count} en el scrape anterior (< 80%). "
                    f"Revisa los scrapers antes de sobreescribir products.json."
                )
                sys.exit(1)
        except Exception as _e:
            print(f"  Aviso safeguard: {_e}")

    # Limpiar
    df = limpiar_dataset(todos)
    if df.empty:
        print("  Sin datos tras limpieza.")
        sys.exit(1)

    # Guardia: no guardar si ninguna tienda tiene datos frescos de hoy.
    # Si los cuatro scrapers fallan a la vez, es un fallo crítico — no enmascararlo
    # guardando un fichero con nombre de hoy y datos de hace días.
    _hoy_str = datetime.now().strftime("%Y-%m-%d")
    if "fecha_scraping" in df.columns and "tienda" in df.columns:
        _tiendas_frescas = set(
            df.loc[df["fecha_scraping"] == _hoy_str, "tienda"].dropna().unique()
        )
    else:
        _tiendas_frescas = set()

    if not _tiendas_frescas:
        _tiendas_todas = set(df["tienda"].dropna().unique()) if "tienda" in df.columns else set()
        print(
            f"\nERROR: ninguna tienda tiene datos frescos de hoy ({_hoy_str}).\n"
            f"  Tiendas en dataset (todas con datos viejos): {sorted(_tiendas_todas)}\n"
            "  No se guarda un dataset nuevo con nombre de hoy.\n"
            "  Revisa los scrapers: que los cuatro fallen a la vez es inusual."
        )
        sys.exit(1)

    # Guardar
    csv_path, json_path = guardar_dataset(df)
    print(f"\n  Guardado: {json_path}")

    mostrar_resumen(df)

    duracion = time.time() - inicio
    print(f"\n  Tiempo total: {duracion:.1f}s")
    print(f"\n  SIGUIENTE: python build.py")
