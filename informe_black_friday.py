"""
informe_black_friday.py — Cifras del informe «Black Friday en suplementos».

Saca, desde data/price_history.json, cómo se movieron los precios de cada producto
(mismo ID = mismo formato, misma tienda) frente a lo que costaban antes de noviembre:

  - subida previa: a primeros de noviembre (antes de CAMPANA_INICIO) ya costaba un 5 % o más
    por encima de su precio habitual
  - mejor precio de la campaña (CAMPANA_INICIO..CAMPANA_FIN) clasificado con black_friday.py
  - «rebaja sobre precio inflado»: subió antes y en la campaña volvió a su precio de siempre
    (o siguió más caro)

Desglose global, por tienda y por tipo de producto, con ejemplos. El desglose por tienda
NO se publica en la web: es para decidir qué se cuenta en el informe.

Uso:
    python informe_black_friday.py                      # resumen en pantalla
    python informe_black_friday.py --json salida.json   # además, todo en JSON
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict

import black_friday as bf

HISTORY = os.path.join("data", "price_history.json")
PRODUCTS = os.path.join("data", "products.json")
TIPOS = {"proteina-whey": "Proteína", "creatina": "Creatina", "bcaa": "BCAA", "pre-entreno": "Pre-entreno"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _cargar():
    with open(HISTORY, encoding="utf-8") as f:
        historial = json.load(f)
    with open(PRODUCTS, encoding="utf-8") as f:
        productos = json.load(f)["products"]
    return historial, productos


def analizar_producto(entradas: list[dict], tienda: str) -> dict | None:
    """Cifras de un producto en una tienda, o None si no hay referencia de antes de noviembre."""
    ref = bf.referencia(entradas, tienda)
    if not ref:
        return None
    habitual = ref["habitual"]
    pre = bf._precios_por_fecha(entradas, tienda, bf.REFERENCIA_FIN, bf.CAMPANA_INICIO)
    fin_campana = bf.CAMPANA_FIN + "~"  # incluye el propio CAMPANA_FIN en la comparación de cadenas
    campana = bf._precios_por_fecha(entradas, tienda, bf.CAMPANA_INICIO, fin_campana)

    pre_nov = statistics.median(pre.values()) if pre else None
    subida_previa = pre_nov is not None and pre_nov >= habitual * (1 + bf.UMBRAL)
    out = {
        "habitual":      round(habitual, 2),
        "minimo_30":     round(ref["minimo_30"], 2),
        "pre_nov":       round(pre_nov, 2) if pre_nov is not None else None,
        "subida_previa": subida_previa,
        "subida_pct":    round((pre_nov / habitual - 1) * 100, 1) if pre_nov else None,
        "min_campana":   None,
        "estado_campana": None,
        "rebaja_pct":    None,
        "inflado":       False,
    }
    if campana:
        min_c = min(campana.values())
        res = bf.clasificar(min_c, ref)
        if res:
            out.update(min_campana=round(min_c, 2), estado_campana=res["estado"], rebaja_pct=res["rebaja_pct"])
            out["inflado"] = subida_previa and res["estado"] in ("precio_habitual", "mas_caro")
    return out


def _resumen(filas: list[dict]) -> dict:
    n = len(filas)
    con_campana = [f for f in filas if f["estado_campana"]]
    nc = len(con_campana)
    reales = [f for f in con_campana if f["estado_campana"] == "rebaja_real"]

    def pct(x, total):
        return round(100 * x / total, 1) if total else None

    return {
        "productos": n,
        "con_precio_en_campana": nc,
        "pct_subida_previa": pct(sum(f["subida_previa"] for f in filas), n),
        "pct_rebaja_real": pct(len(reales), nc),
        "pct_rebajado": pct(sum(f["estado_campana"] == "rebajado" for f in con_campana), nc),
        "pct_precio_habitual": pct(sum(f["estado_campana"] == "precio_habitual" for f in con_campana), nc),
        "pct_mas_caro": pct(sum(f["estado_campana"] == "mas_caro" for f in con_campana), nc),
        "pct_rebaja_sobre_inflado": pct(sum(f["inflado"] for f in con_campana), nc),
        "rebaja_real_media_pct": round(statistics.mean(f["rebaja_pct"] for f in reales), 1) if reales else None,
    }


def informe() -> dict:
    historial, productos = _cargar()
    por_id = defaultdict(list)
    for e in historial:
        por_id[e["producto_id"]].append(e)

    filas = []
    for p in productos:
        if (p.get("peso_kg") or 0) < bf.PESO_MINIMO_KG:
            continue
        tienda = p.get("tienda_mas_barata")
        res = analizar_producto(por_id.get(p["id"], []), tienda)
        if res:
            filas.append({
                "id": p["id"], "nombre": p.get("nombre_display") or p.get("nombre_normalizado"),
                "tienda": tienda, "tipo": TIPOS.get(p.get("categoria"), p.get("categoria")), **res,
            })

    por_tienda = defaultdict(list)
    por_tipo = defaultdict(list)
    for f in filas:
        por_tienda[f["tienda"]].append(f)
        por_tipo[f["tipo"]].append(f)

    ejemplos = {
        "mayores_rebajas_reales": sorted(
            [f for f in filas if f["estado_campana"] == "rebaja_real"], key=lambda f: -f["rebaja_pct"])[:15],
        "mayores_subidas_previas": sorted(
            [f for f in filas if f["subida_previa"]], key=lambda f: -(f["subida_pct"] or 0))[:15],
        "rebajas_sobre_precio_inflado": [f for f in filas if f["inflado"]][:30],
    }
    return {
        "referencia_fin": bf.REFERENCIA_FIN,
        "campana": [bf.CAMPANA_INICIO, bf.CAMPANA_FIN],
        "global": _resumen(filas),
        "por_tienda": {t: _resumen(v) for t, v in sorted(por_tienda.items())},
        "por_tipo": {t: _resumen(v) for t, v in sorted(por_tipo.items())},
        "ejemplos": ejemplos,
    }


def _imprimir(r: dict) -> None:
    g = r["global"]
    print(f"Referencia: precios antes del {r['referencia_fin']} · campaña {r['campana'][0]} – {r['campana'][1]}")
    print(f"Productos con historial suficiente: {g['productos']} "
          f"(con precio en la campaña: {g['con_precio_en_campana']})\n")

    cab = f"{'':14}{'prod.':>6}{'subida previa':>15}{'rebaja real':>13}{'de siempre':>12}{'más caro':>10}{'s/inflado':>11}"
    print(cab)

    def fila(nombre, s):
        def f(v):
            return "—" if v is None else f"{v:.0f} %"
        print(f"{nombre:14}{s['productos']:>6}{f(s['pct_subida_previa']):>15}{f(s['pct_rebaja_real']):>13}"
              f"{f(s['pct_precio_habitual']):>12}{f(s['pct_mas_caro']):>10}{f(s['pct_rebaja_sobre_inflado']):>11}")

    fila("TOTAL", g)
    print()
    for t, s in r["por_tienda"].items():
        fila(t, s)
    print()
    for t, s in r["por_tipo"].items():
        fila(t, s)
    if not g["con_precio_en_campana"]:
        print("\nLa campaña aún no ha empezado: solo hay datos de subida previa (primeros de noviembre).")
    print("\nMayores subidas previas:")
    for e in r["ejemplos"]["mayores_subidas_previas"][:8]:
        print(f"  {e['tienda']:12} {e['nombre'][:45]:45} {e['habitual']:>7.2f} → {e['pre_nov']:>7.2f} €  (+{e['subida_pct']:.0f} %)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", help="guardar el informe completo en esta ruta")
    args = ap.parse_args()
    r = informe()
    _imprimir(r)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"\nGuardado en {args.json}")


if __name__ == "__main__":
    main()
