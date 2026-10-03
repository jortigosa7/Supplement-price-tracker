"""
test_nutritienda_live.py -- Test en vivo del scraper de Nutritienda.

Fuerza fetch fresco (elimina caché) de 8 URLs específicas y comprueba que
el scraper extrae precio y estado de stock correctos.

Regla: un precio de formato equivocado es FALLO; excluir el producto es ACEPTABLE.

Uso:
    python test_nutritienda_live.py
"""

import io
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from scrapers.detail_cache import _cache_path
from scrapers.nutritienda import _scrape_detalle

# ---------------------------------------------------------------------------
# Casos verificados manualmente (01-oct-2026)
# precio_esperado: float → precio correcto del tamaño del nombre_listing
#                  None  → solo importa el estado (agotado)
# estado_esperado: "InStock" | "Agotado"
# Nota: EXCLUIDO es siempre aceptable para casos InStock (no penaliza, pero
#       un precio equivocado sí es FALLO)
# ---------------------------------------------------------------------------
CASOS = [
    {
        "slug":            "olimp/whey-protein-complex-100",
        "url":             "https://www.nutritienda.com/es/olimp/whey-protein-complex-100-",
        "nombre_listing":  "WHEY PROTEIN COMPLEX 100% 2270 g",
        "precio_esperado": 99.50,
        "estado_esperado": "InStock",
    },
    {
        "slug":            "biotech-usa/iso-whey-platinum",
        "url":             "https://www.nutritienda.com/es/biotech-usa/iso-whey-platinum",
        "nombre_listing":  "Iso Whey Platinum 908 g",
        "precio_esperado": 46.90,
        "estado_esperado": "InStock",
    },
    {
        "slug":            "mega-plus/isolate-concept",
        "url":             "https://www.nutritienda.com/es/mega-plus/isolate-concept",
        "nombre_listing":  "Isolate Concept 2000 g",
        "precio_esperado": 58.48,
        "estado_esperado": "InStock",
    },
    {
        "slug":            "paleobull/panacea",
        "url":             "https://www.nutritienda.com/es/paleobull/panacea",
        "nombre_listing":  "Panacea 750 g",
        "precio_esperado": 37.95,
        "estado_esperado": "InStock",
    },
    {
        "slug":            "biotech-usa/hydro-whey-zero",
        "url":             "https://www.nutritienda.com/es/biotech-usa/hydro-whey-zero",
        "nombre_listing":  "Hydro Whey Zero 1816 g",
        "precio_esperado": 86.90,
        "estado_esperado": "InStock",
    },
    {
        "slug":            "rule1/r1-gain",
        "url":             "https://www.nutritienda.com/es/rule1/r1-gain",
        "nombre_listing":  "R1 Gain",
        "precio_esperado": None,
        "estado_esperado": "Agotado",
        "acepta_excluido": True,  # 404 = producto eliminado del catálogo
    },
    {
        "slug":            "vplab/100-platinum-whey",
        "url":             "https://www.nutritienda.com/es/vplab-nutrition/100-platinum-whey",
        "nombre_listing":  "100% Platinum Whey",
        "precio_esperado": None,
        "estado_esperado": "Agotado",
        "acepta_excluido": True,  # 404 = producto eliminado del catálogo
    },
    {
        "slug":            "battery/bcaa-2-1-1",
        "url":             "https://www.nutritienda.com/es/battery/battery-bcaa-2-1-1",
        "nombre_listing":  "Battery BCAA 2:1:1",
        "precio_esperado": None,
        "estado_esperado": "Agotado",
        "acepta_excluido": True,  # 404 = producto eliminado del catálogo
    },
    {
        "slug":            "muscletech/cell-tech-performance-series",
        "url":             "https://www.nutritienda.com/es/muscletech/cell-tech-performance-series",
        "nombre_listing":  "CELL TECH PERFORMANCE SERIES 2270 g",
        "precio_esperado": None,
        "estado_esperado": "InStock",
        "acepta_excluido": True,  # EXCLUIDO es aceptable (tamaño-ambiguo)
    },
    {
        "slug":            "biotech-usa/nitrox-therapy",
        "url":             "https://www.nutritienda.com/es/biotech-usa/nitrox-therapy",
        "nombre_listing":  "NITROX THERAPY 340 g",
        "precio_esperado": None,
        "estado_esperado": "InStock",
        "acepta_excluido": True,  # EXCLUIDO es aceptable (tamaño-ambiguo)
    },
]


def borrar_cache(url: str):
    try:
        path = _cache_path("nutritienda", url)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def evaluar(caso: dict, precio_obtenido, estado_obtenido: str) -> tuple[bool, str]:
    """
    Reglas:
    - Agotado esperado → estado debe ser Agotado (precio irrelevante)
    - InStock esperado:
        * EXCLUIDO    → ACEPTABLE (pass)
        * Agotado     → FALLO
        * precio OK   → PASS
        * precio malo → FALLO (precio de otro formato)
    """
    precio_esp  = caso["precio_esperado"]
    estado_esp  = caso["estado_esperado"]

    if estado_esp == "Agotado":
        if estado_obtenido == "Agotado":
            return True, "PASS (agotado correcto)"
        if estado_obtenido == "EXCLUIDO" and caso.get("acepta_excluido"):
            return True, "PASS (404 — producto eliminado del catálogo)"
        return False, f"FALLO: esperado Agotado, obtenido {estado_obtenido}"

    # InStock esperado
    if estado_obtenido == "EXCLUIDO":
        return True, "PASS (excluido — aceptable)"

    if estado_obtenido == "Agotado":
        return False, f"FALLO: esperado InStock, obtenido Agotado"

    # InStock obtenido — verificar precio
    if precio_esp is not None:
        if precio_obtenido is None:
            return False, f"FALLO: sin precio, esperado {precio_esp}"
        diff_pct = abs(precio_obtenido - precio_esp) / precio_esp
        if diff_pct > 0.02:
            return False, f"FALLO: precio {precio_obtenido:.2f} difiere {diff_pct*100:.1f}% de esperado {precio_esp}"
        return True, f"PASS ({precio_obtenido:.2f} EUR, diff {diff_pct*100:.1f}%)"

    return True, f"PASS ({estado_obtenido})"


def main():
    print("\n" + "=" * 70)
    print("  TEST LIVE — Scraper Nutritienda")
    print("=" * 70)

    print("\nBorrando caché para forzar fetch fresco...")
    for caso in CASOS:
        borrar_cache(caso["url"])

    resultados = []
    for i, caso in enumerate(CASOS, 1):
        print(f"\n[{i}/{len(CASOS)}] {caso['slug']}")

        _, enrichment = _scrape_detalle(caso["url"], nombre_listing=caso["nombre_listing"])

        precio_v      = enrichment.get("_precio_variante")
        sin_confirmar = enrichment.get("_precio_sin_confirmar", False)
        agotado       = enrichment.get("_agotado", False)

        if agotado:
            estado = "Agotado"
        elif precio_v is not None and not sin_confirmar:
            estado = "InStock"
        else:
            estado = "EXCLUIDO"

        ok, motivo = evaluar(caso, precio_v, estado)
        resultados.append({
            "slug":            caso["slug"],
            "precio_esp":      caso["precio_esperado"],
            "estado_esp":      caso["estado_esperado"],
            "precio_obtenido": precio_v,
            "estado_obtenido": estado,
            "ok":              ok,
            "motivo":          motivo,
        })
        print(f"  -> precio={precio_v}  estado={estado}  {motivo}")

    # Tabla resumen
    W = 42
    print("\n" + "=" * 70)
    print("  TABLA RESUMEN")
    print("=" * 70)
    print(f"{'slug':<{W}} {'Esp.€':>7} {'Esp.est':<8} {'Obt.€':>7} {'Obt.est':<8} Res.")
    print("-" * 70)

    fallos = []
    for r in resultados:
        pe = f"{r['precio_esp']:.2f}"  if r["precio_esp"]      is not None else "---"
        po = f"{r['precio_obtenido']:.2f}" if r["precio_obtenido"] is not None else "---"
        res = "OK" if r["ok"] else "FALLO"
        slug = r["slug"][-W:] if len(r["slug"]) > W else r["slug"]
        print(f"{slug:<{W}} {pe:>7} {r['estado_esp']:<8} {po:>7} {r['estado_obtenido']:<8} {res}")
        if not r["ok"]:
            fallos.append(r)

    print()
    if not fallos:
        print("  TODOS OK — puedes continuar con el scrape completo.")
        sys.exit(0)
    else:
        print(f"  {len(fallos)} FALLO(S) — NO hagas push hasta resolver:")
        for f in fallos:
            print(f"    - {f['slug']}: {f['motivo']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
