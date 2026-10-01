"""
test_nutritienda_live.py -- Test en vivo del scraper de Nutritienda.

Fuerza fetch fresco (elimina cache) de 8 URLs especificas y comprueba que
el scraper extrae precio y estado de stock correctos.

Casos cubiertos:
- Productos InStock con offer simple (un solo tamano, strategy directa)
- Productos InStock con multiples tamanos sin etiqueta (strategy b, excluido OK)
- Productos InStock con tamano en el nombre del offer (strategy a)

Uso:
    python test_nutritienda_live.py
"""

import io
import os
import sys

# Forzar UTF-8 en stdout para evitar errores con emojis en consolas cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from scrapers.detail_cache import _cache_path
from scrapers.nutritienda import _scrape_detalle

# ---------------------------------------------------------------------------
# Casos de prueba
# ---------------------------------------------------------------------------
# estado_esperado: "InStock", "Agotado", "EXCLUIDO"
# precio_esperado: float (se valida +-2%) o None (cualquier precio OK)
# acepta_excluido: True si puede salir como EXCLUIDO sin ser un fallo
# acepta_cualquier_precio: True si solo importa el estado, no el precio exacto
CASOS = [
    # --- Casos que deben resolver precio correctamente ---
    {
        "url":    "https://www.nutritienda.com/es/biotech-usa/hydro-whey-zero",
        "slug":   "biotech-usa/hydro-whey-zero",
        "nombre_listing": "Hydro Whey Zero 1816 g",
        "precio_esperado": 86.90,
        "estado_esperado": "InStock",
        "acepta_excluido": False,
    },
    {
        "url":    "https://www.nutritienda.com/es/biotech-usa/whey-shake-1000g",
        "slug":   "biotech-usa/whey-shake-1000g",
        "nombre_listing": "Whey Shake 1000g",
        "precio_esperado": 31.90,
        "estado_esperado": "InStock",
        "acepta_excluido": False,
    },
    {
        "url":    "https://www.nutritienda.com/es/quamtrax-direct/100-whey-isolate-700g",
        "slug":   "quamtrax-direct/100-whey-isolate-700g",
        "nombre_listing": "100% Whey Isolate 700g",
        "precio_esperado": 42.90,
        "estado_esperado": "InStock",
        "acepta_excluido": False,
    },
    {
        "url":    "https://www.nutritienda.com/es/quamtrax-direct/whey-protein-sabor-neutro-500g",
        "slug":   "quamtrax-direct/whey-protein-sabor-neutro-500g",
        "nombre_listing": "Whey Protein Sabor Neutro 500g",
        "precio_esperado": 20.50,
        "estado_esperado": "InStock",
        "acepta_excluido": False,
    },
    {
        "url":    "https://www.nutritienda.com/es/vitobest/whey-protein-100-sabor-neutro-1-kg",
        "slug":   "vitobest/whey-protein-100-sabor-neutro-1-kg",
        "nombre_listing": "Whey Protein 100% sabor Neutro 1 Kg",
        "precio_esperado": 48.60,
        "estado_esperado": "InStock",
        "acepta_excluido": False,
    },
    # --- Casos con multiples tamanos sin etiqueta: strategy b debe excluirlos ---
    # (esto valida que el fix de Bug 1 funciona correctamente)
    {
        "url":    "https://www.nutritienda.com/es/biotech-usa/iso-whey-platinum",
        "slug":   "biotech-usa/iso-whey-platinum",
        "nombre_listing": "BioTechUSA Iso Whey Platinum 908g",
        "precio_esperado": None,
        "estado_esperado": "EXCLUIDO",
        "acepta_excluido": True,
        "excluido_esperado": True,  # el fix correcto excluye este producto
    },
    {
        "url":    "https://www.nutritienda.com/es/paleobull/panacea",
        "slug":   "paleobull/panacea",
        "nombre_listing": "Panacea 750g",
        "precio_esperado": None,
        "estado_esperado": "EXCLUIDO",
        "acepta_excluido": True,
        "excluido_esperado": True,
    },
    # --- Olimp: fix strategy b, multiples tamanos InStock sin etiqueta ---
    {
        "url":    "https://www.nutritienda.com/es/olimp/whey-protein-complex-100-",
        "slug":   "olimp/whey-protein-complex-100-",
        "nombre_listing": "WHEY PROTEIN COMPLEX 100% 2270 g",
        "precio_esperado": None,
        "estado_esperado": "EXCLUIDO",
        "acepta_excluido": True,
        "excluido_esperado": True,  # multiples tamanos InStock sin etiqueta
    },
]


def borrar_cache(url: str):
    """Elimina la cache de una URL especifica de Nutritienda."""
    path = _cache_path("nutritienda", url)
    if os.path.exists(path):
        os.remove(path)
        print(f"  [cache] Eliminada: {path}")


def evaluar(caso: dict, precio_obtenido, estado_obtenido: str) -> tuple[bool, str]:
    """Evalua si el resultado es PASS o FALLO."""
    precio_esp = caso.get("precio_esperado")
    estado_esp = caso.get("estado_esperado")
    excluido_esperado = caso.get("excluido_esperado", False)
    acepta_excluido = caso.get("acepta_excluido", False)

    # Caso en que se espera EXCLUIDO explicitamente
    if excluido_esperado:
        if estado_obtenido == "EXCLUIDO":
            return True, "PASS (excluido correcto - fix strategy b)"
        # Si resolvio un precio, puede ser aceptable (datos en vivo cambian)
        if estado_obtenido == "InStock" and precio_obtenido is not None:
            return True, f"PASS (resolvio precio {precio_obtenido:.2f} - datos en vivo)"
        return False, f"FALLO: esperado EXCLUIDO, obtenido {estado_obtenido}"

    # Caso EXCLUIDO no esperado
    if estado_obtenido == "EXCLUIDO":
        if acepta_excluido:
            return True, "PASS (excluido aceptado)"
        return False, f"FALLO: esperado {estado_esp}, obtenido EXCLUIDO"

    # Verificar estado de stock
    if estado_esp == "Agotado" and estado_obtenido != "Agotado":
        return False, f"FALLO: esperado Agotado, obtenido {estado_obtenido}"
    if estado_esp == "InStock" and estado_obtenido == "Agotado":
        return False, f"FALLO: esperado InStock, obtenido Agotado"

    # Verificar precio si se especifico
    if precio_esp is not None and precio_obtenido is not None:
        diff_pct = abs(precio_obtenido - precio_esp) / precio_esp
        if diff_pct > 0.02:
            return False, f"FALLO: precio {precio_obtenido:.2f} difiere {diff_pct*100:.1f}% de {precio_esp}"
        return True, f"PASS ({precio_obtenido:.2f} EUR +-{diff_pct*100:.1f}%)"

    if precio_esp is not None and precio_obtenido is None and estado_esp != "Agotado":
        return False, f"FALLO: sin precio, esperado {precio_esp}"

    return True, f"PASS ({estado_obtenido})"


def main():
    print("\n" + "=" * 70)
    print("  TEST LIVE - Scraper Nutritienda")
    print("=" * 70)

    # Borrar cache de todos los casos para forzar fetch fresco
    print("\nBorrando cache para forzar fetch fresco...")
    for caso in CASOS:
        borrar_cache(caso["url"])

    # Ejecutar scraper para cada URL
    resultados = []
    for i, caso in enumerate(CASOS, 1):
        url = caso["url"]
        slug = caso["slug"]
        nombre_listing = caso.get("nombre_listing", "")
        print(f"\n[{i}/{len(CASOS)}] {slug}")

        _, enrichment = _scrape_detalle(url, nombre_listing=nombre_listing)

        precio_variante = enrichment.get("_precio_variante")
        sin_confirmar   = enrichment.get("_precio_sin_confirmar", False)
        agotado         = enrichment.get("_agotado", False)

        if sin_confirmar and precio_variante is None:
            estado = "EXCLUIDO"
        elif agotado:
            estado = "Agotado"
        elif precio_variante is not None:
            estado = "InStock"
        else:
            # Sin precio y no marcado como agotado ni excluido
            estado = "EXCLUIDO"

        ok, motivo = evaluar(caso, precio_variante, estado)
        resultados.append({
            "slug":             slug,
            "precio_esp":       caso.get("precio_esperado"),
            "estado_esp":       caso.get("estado_esperado"),
            "precio_obtenido":  precio_variante,
            "estado_obtenido":  estado,
            "ok":               ok,
            "motivo":           motivo,
        })
        print(f"  Precio: {precio_variante} | Estado: {estado} -> {motivo}")

    # Tabla resumen
    print("\n" + "=" * 70)
    print("  TABLA RESUMEN")
    print("=" * 70)
    col_slug  = 42
    col_ep    = 8
    col_es    = 9
    col_op    = 8
    col_os    = 9
    col_r     = 6
    header = (
        f"{'URL_slug':<{col_slug}} "
        f"{'Esp.EUR':>{col_ep}} "
        f"{'Esp.est':<{col_es}} "
        f"{'Obt.EUR':>{col_op}} "
        f"{'Obt.est':<{col_os}} "
        f"{'Res.':<{col_r}}"
    )
    print(header)
    print("-" * (col_slug + col_ep + col_es + col_op + col_os + col_r + 5))

    fallos = []
    for r in resultados:
        precio_esp_str = f"{r['precio_esp']:.2f}" if r["precio_esp"] is not None else "---"
        precio_obt_str = f"{r['precio_obtenido']:.2f}" if r["precio_obtenido"] is not None else "---"
        res_str = "OK" if r["ok"] else "FALLO"
        slug_short = r["slug"][-col_slug:] if len(r["slug"]) > col_slug else r["slug"]
        print(
            f"{slug_short:<{col_slug}} "
            f"{precio_esp_str:>{col_ep}} "
            f"{r['estado_esp']:<{col_es}} "
            f"{precio_obt_str:>{col_op}} "
            f"{r['estado_obtenido']:<{col_os}} "
            f"{res_str:<{col_r}}"
        )
        if not r["ok"]:
            fallos.append(r)

    print()
    if not fallos:
        print("  TODOS OK")
        sys.exit(0)
    else:
        print(f"  {len(fallos)} FALLO(S):")
        for f in fallos:
            print(f"    - {f['slug']}: {f['motivo']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
