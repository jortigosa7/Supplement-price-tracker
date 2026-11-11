"""
Black Friday: qué rebajas de suplementos son reales.

Cada producto se compara consigo mismo (mismo ID = mismo formato, misma tienda, en €)
con lo que costaba ANTES de las campañas de noviembre:

  - precio habitual: mediana de los 90 días anteriores a REFERENCIA_FIN
  - mínimo previo:   precio más bajo de los 30 días anteriores a REFERENCIA_FIN

La referencia es fija y anterior a noviembre por dos motivos: las tiendas empiezan las
promociones semanas antes del viernes, y con una ventana móvil una oferta que dura varios
días dejaría de contar como rebaja al segundo día. Así, si una tienda sube un precio a
primeros de noviembre y luego lo "rebaja" al precio de octubre, sale como precio de siempre.

Lo usan build.py (página /black-friday/) e informe_black_friday.py (cifras del informe).
No se usa el "precio antes" que anuncian las tiendas: no lo tenemos y es justo lo que
se quiere comprobar.
"""

import statistics
from collections import Counter
from datetime import date, timedelta

REFERENCIA_FIN = "2026-11-01"   # primer día que ya NO cuenta como "antes de la campaña"
CAMPANA_INICIO = "2026-11-14"   # para el informe: precios "de Black Friday"
CAMPANA_FIN = "2026-12-01"      # Cyber Monday incluido
DIAS_PAGINA_ABIERTA = 7         # días tras CAMPANA_FIN que la página sigue con listados

VENTANA_HABITUAL = 90
VENTANA_MINIMO = 30
MIN_FECHAS_HABITUAL = 8         # observaciones mínimas en 90 días para fiarse del habitual
MIN_FECHAS_MINIMO = 2           # y en los 30 días del mínimo previo
UMBRAL = 0.05                   # ±5 % sobre el habitual separa "rebajado"/"más caro" de "igual"
MAX_CAIDA = 0.50                # una caída mayor del 50 % se trata como error de scraping
PESO_MINIMO_KG = 0.15           # mismo corte que _excluir_producto en build.py
TOLERANCIA = 0.005

ESTADOS = ("rebaja_real", "rebajado", "precio_habitual", "mas_caro")


def _precios_por_fecha(entradas: list[dict], tienda: str, desde: str, hasta: str) -> dict[str, float]:
    """Un precio por fecha (el más bajo), de la tienda dada, con desde <= fecha < hasta."""
    out: dict[str, float] = {}
    for e in entradas:
        fecha = e.get("fecha", "")
        precio = e.get("precio")
        if e.get("tienda") != tienda or precio is None or not (desde <= fecha < hasta):
            continue
        out[fecha] = min(float(precio), out.get(fecha, float(precio)))
    return out


def referencia(entradas: list[dict], tienda: str, ref_fin: str = REFERENCIA_FIN) -> dict | None:
    """Precio habitual y mínimo previo antes de ref_fin, o None si el historial no basta."""
    fin = date.fromisoformat(ref_fin)
    ini_90 = (fin - timedelta(days=VENTANA_HABITUAL)).isoformat()
    ini_30 = (fin - timedelta(days=VENTANA_MINIMO)).isoformat()
    serie_90 = _precios_por_fecha(entradas, tienda, ini_90, ref_fin)
    serie_30 = {f: v for f, v in serie_90.items() if f >= ini_30}
    if len(serie_90) < MIN_FECHAS_HABITUAL or len(serie_30) < MIN_FECHAS_MINIMO:
        return None
    return {
        "habitual":  statistics.median(serie_90.values()),
        "minimo_30": min(serie_30.values()),
        "n_fechas":  len(serie_90),
    }


def clasificar(precio_hoy: float, ref: dict) -> dict | None:
    """Estado del precio de hoy frente a la referencia; None si parece un error de datos."""
    habitual = ref["habitual"]
    if not habitual or precio_hoy <= 0:
        return None
    variacion = precio_hoy / habitual - 1          # negativa = más barato que de costumbre
    if variacion < -MAX_CAIDA:
        return None
    if precio_hoy < ref["minimo_30"] - TOLERANCIA and variacion <= -UMBRAL:
        estado = "rebaja_real"
    elif variacion <= -UMBRAL:
        estado = "rebajado"
    elif variacion >= UMBRAL:
        estado = "mas_caro"
    else:
        estado = "precio_habitual"
    return {
        "estado":     estado,
        "rebaja_pct": round(-variacion * 100, 1),
        "habitual":   round(habitual, 2),
        "minimo_30":  round(ref["minimo_30"], 2),
    }


def _precio_de_tienda(producto: dict, tienda: str) -> dict | None:
    for pr in producto.get("precios", []):
        if pr.get("tienda") == tienda and pr.get("precio_eur") and not pr.get("agotado") \
                and not pr.get("sin_precio"):
            return pr
    return None


def analizar(productos: list[dict], hist_by_id: dict, tiendas_afiliadas: set[str],
             ids_excluidos: set[str] | None = None, ref_fin: str = REFERENCIA_FIN) -> dict:
    """
    Clasifica cada producto (en su tienda más barata) frente a su referencia.
    Las cifras agregadas cubren todas las tiendas; los listados con enlace, solo afiliadas.
    """
    ids_excluidos = ids_excluidos or set()
    por_estado: Counter = Counter()
    por_categoria: dict[str, Counter] = {}
    por_tienda: dict[str, Counter] = {}
    listados: dict[str, list[dict]] = {"rebaja_real": [], "rebajado": []}

    for p in productos:
        if p.get("agotado") or p.get("sin_precio") or p.get("id") in ids_excluidos:
            continue
        if (p.get("peso_kg") or 0) < PESO_MINIMO_KG:
            continue
        tienda = p.get("tienda_mas_barata")
        pr = _precio_de_tienda(p, tienda)
        if not pr:
            continue
        ref = referencia(hist_by_id.get(p["id"], []), tienda, ref_fin)
        if not ref:
            continue
        res = clasificar(float(pr["precio_eur"]), ref)
        if not res:
            continue
        estado = res["estado"]
        por_estado[estado] += 1
        por_categoria.setdefault(p.get("categoria", "?"), Counter())[estado] += 1
        por_tienda.setdefault(tienda, Counter())[estado] += 1
        if estado in listados and tienda in tiendas_afiliadas:
            listados[estado].append({
                "id":           p["id"],
                "nombre":       p.get("nombre_display") or p.get("nombre_normalizado"),
                "categoria":    p.get("categoria"),
                "tienda":       tienda,
                "precio":       float(pr["precio_eur"]),
                "url_afiliado": pr.get("url_afiliado"),
                "pagina_url":   p.get("pagina_url"),
                "valoraciones": int(p.get("store_rating_count") or 0),
                **res,
            })

    for estado in listados:
        listados[estado].sort(key=lambda x: (-x["rebaja_pct"], -x["valoraciones"]))
    total = sum(por_estado.values())
    return {
        "referencia_fin": ref_fin,
        "total":          total,
        "por_estado":     {e: por_estado.get(e, 0) for e in ESTADOS},
        "pct_estado":     {e: round(100 * por_estado.get(e, 0) / total) if total else 0 for e in ESTADOS},
        "por_categoria":  {c: {e: n.get(e, 0) for e in ESTADOS} for c, n in sorted(por_categoria.items())},
        "por_tienda":     {t: {e: n.get(e, 0) for e in ESTADOS} for t, n in sorted(por_tienda.items())},
        "rebajas_reales": listados["rebaja_real"],
        "rebajados":      listados["rebajado"],
    }


def pagina_abierta(fecha_hoy: str) -> bool:
    """La página enseña listados hasta una semana después de Cyber Monday."""
    fin = date.fromisoformat(CAMPANA_FIN) + timedelta(days=DIAS_PAGINA_ABIERTA)
    return fecha_hoy <= fin.isoformat()
