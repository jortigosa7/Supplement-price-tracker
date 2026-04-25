"""
build_additions.py — Sparklines y ticker de variación de precios para StackFit.

Funciones exportadas:
    compute_spark_data(productos_web)  → modifica la lista in-place, añade spark_svg y spark_min
    build_ticker_items(productos_web)  → devuelve lista de 12 items con mayor variación de precio
"""

import json
import math
import os

PRICE_HISTORY_PATH = os.path.join("data", "price_history.json")

SPARK_W = 80
SPARK_H = 28
SPARK_STROKE = "#c8ff4d"
SPARK_STROKE_WIDTH = 1.5


def _load_history() -> dict[str, list[dict]]:
    """Carga price_history.json y devuelve {producto_id: [entradas ordenadas por fecha]}."""
    if not os.path.exists(PRICE_HISTORY_PATH):
        return {}
    with open(PRICE_HISTORY_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    by_id: dict[str, list[dict]] = {}
    for entry in raw:
        pid = entry.get("producto_id", "")
        if not pid:
            continue
        by_id.setdefault(pid, []).append(entry)
    # Ordenar cada producto por fecha ascendente
    for pid in by_id:
        by_id[pid].sort(key=lambda e: e.get("fecha", ""))
    return by_id


_COLOR_UP   = "#ef4444"  # rojo — precio subió
_COLOR_DOWN = "#22c55e"  # verde — precio bajó o igual


def _build_spark_svg(prices: list[float]) -> str:
    """Genera un SVG sparkline inline con segmentos coloreados por dirección de precio.

    Verde = precio bajó o se mantuvo respecto al punto anterior.
    Rojo  = precio subió respecto al punto anterior.
    Eje Y estándar: precios altos en la parte superior del gráfico.
    """
    if len(prices) < 2:
        return ""
    lo = min(prices)
    hi = max(prices)
    span = hi - lo if hi != lo else 1.0

    def _x(i):
        return round(SPARK_W * i / (len(prices) - 1), 2)

    def _y(v):
        # Precio alto → y pequeño (arriba del SVG): gráfico estándar
        return round(SPARK_H - SPARK_H * (v - lo) / span, 2)

    # Generar un <line> por segmento coloreado por dirección
    segments = []
    for i in range(len(prices) - 1):
        v1, v2 = prices[i], prices[i + 1]
        x1, y1 = _x(i), _y(v1)
        x2, y2 = _x(i + 1), _y(v2)
        color = _COLOR_DOWN if v2 <= v1 else _COLOR_UP
        segments.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{SPARK_STROKE_WIDTH}" '
            f'stroke-linecap="round"/>'
        )

    # Punto en el precio actual, con el color del último movimiento
    last_color = _COLOR_DOWN if prices[-1] <= prices[-2] else _COLOR_UP
    lx, ly = _x(len(prices) - 1), _y(prices[-1])
    dot = f'<circle cx="{lx}" cy="{ly}" r="2.5" fill="{last_color}"/>'

    return (
        f'<svg viewBox="0 0 {SPARK_W} {SPARK_H}" width="{SPARK_W}" height="{SPARK_H}" '
        f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        + "".join(segments) + dot +
        f'</svg>'
    )


def compute_spark_data(productos_web: list[dict]) -> list[dict]:
    """
    Para cada producto en productos_web, añade:
      - spark_svg  (str): SVG inline del sparkline de precio €/kg. Vacío si no hay historial.
      - spark_min  (float | None): precio mínimo histórico en €/kg.

    Modifica la lista in-place y también la devuelve.
    """
    history = _load_history()

    for p in productos_web:
        pid = p.get("id", "")
        entries = history.get(pid, [])

        if len(entries) < 2:
            p["spark_svg"] = ""
            p["spark_min"] = None
            continue

        peso_kg = p.get("peso_kg") or 1.0
        # Calcular €/kg por entrada usando el precio de la entrada y el peso del producto
        prices_kg: list[float] = []
        for e in entries:
            precio = e.get("precio")
            if precio is not None and peso_kg > 0:
                try:
                    pkg = float(precio) / float(peso_kg)
                    if pkg > 0 and not math.isnan(pkg):
                        prices_kg.append(round(pkg, 2))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        if len(prices_kg) < 2:
            p["spark_svg"] = ""
            p["spark_min"] = None
            continue

        p["spark_svg"] = _build_spark_svg(prices_kg)
        p["spark_min"] = round(min(prices_kg), 2)

    return productos_web


def build_ticker_items(productos_web: list[dict]) -> list[dict]:
    """
    Devuelve una lista de hasta 12 dicts con los productos que mayor variación
    de precio (en porcentaje) han registrado en el historial.

    Cada dict tiene:
        nombre    (str)   — nombre_normalizado del producto
        precio_kg (float) — precio €/kg actual (precio_por_kg_min)
        delta     (float) — variación % entre precio histórico más alto y actual
                            (positivo = subida, negativo = bajada)
    """
    history = _load_history()

    candidates: list[dict] = []
    for p in productos_web:
        pid = p.get("id", "")
        entries = history.get(pid, [])
        if len(entries) < 2:
            continue

        precio_actual_kg = p.get("precio_por_kg_min")
        if not precio_actual_kg:
            continue

        peso_kg = p.get("peso_kg") or 1.0
        prices_kg: list[float] = []
        for e in entries:
            precio = e.get("precio")
            if precio is not None and peso_kg > 0:
                try:
                    pkg = float(precio) / float(peso_kg)
                    if pkg > 0 and not math.isnan(pkg):
                        prices_kg.append(pkg)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        if len(prices_kg) < 2:
            continue

        precio_maximo = max(prices_kg)
        if precio_maximo > 0:
            delta = round((precio_actual_kg - precio_maximo) / precio_maximo * 100, 1)
        else:
            delta = 0.0

        if abs(delta) < 0.5:
            continue

        candidates.append({
            "nombre":    p["nombre_normalizado"],
            "precio_kg": round(precio_actual_kg, 2),
            "delta":     delta,
        })

    # Ordenar por variación absoluta descendente y devolver los 12 mayores
    candidates.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return candidates[:12]
