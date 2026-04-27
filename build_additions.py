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


_COLOR_BAJADA = "#22c55e"  # verde — precio actual menor o igual al inicial
_COLOR_SUBIDA = "#ef4444"  # rojo  — precio actual mayor que el inicial


def _build_spark_svg(prices: list[float]) -> str:
    """Genera un SVG sparkline inline con color único según tendencia global.

    Verde si el precio actual (último) es <= al precio inicial (primero): línea baja.
    Rojo  si el precio actual es > al precio inicial: línea sube.
    Eje Y estándar: precio alto arriba, precio bajo abajo.
    """
    if len(prices) < 2:
        return ""
    lo = min(prices)
    hi = max(prices)
    span = hi - lo if hi != lo else 1.0

    def _x(i):
        return round(SPARK_W * i / (len(prices) - 1), 2)

    def _y(v):
        # Precio alto → y pequeño (arriba): gráfico estándar
        return round(SPARK_H - SPARK_H * (v - lo) / span, 2)

    # Color único basado en tendencia global (primer precio → último precio)
    color = _COLOR_BAJADA if prices[-1] <= prices[0] else _COLOR_SUBIDA

    points = " ".join(f"{_x(i)},{_y(v)}" for i, v in enumerate(prices))
    lx, ly = _x(len(prices) - 1), _y(prices[-1])

    return (
        f'<svg viewBox="0 0 {SPARK_W} {SPARK_H}" width="{SPARK_W}" height="{SPARK_H}" '
        f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="{SPARK_STROKE_WIDTH}" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx}" cy="{ly}" r="2.5" fill="{color}"/>'
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
        # Agrupar por fecha y tomar el mínimo €/kg del día entre todas las tiendas.
        # Así el último punto del sparkline coincide siempre con el precio mínimo actual
        # y no con la última tienda scrapeada (que puede ser la más cara).
        prices_by_date: dict[str, list[float]] = {}
        for e in entries:
            precio = e.get("precio")
            fecha = e.get("fecha", "")
            if precio is not None and fecha and peso_kg > 0:
                try:
                    pkg = float(precio) / float(peso_kg)
                    if pkg > 0 and not math.isnan(pkg):
                        prices_by_date.setdefault(fecha, []).append(round(pkg, 2))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        prices_kg = [min(v) for _, v in sorted(prices_by_date.items())]

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
        prices_by_date: dict[str, list[float]] = {}
        for e in entries:
            precio = e.get("precio")
            fecha = e.get("fecha", "")
            if precio is not None and fecha and peso_kg > 0:
                try:
                    pkg = float(precio) / float(peso_kg)
                    if pkg > 0 and not math.isnan(pkg):
                        prices_by_date.setdefault(fecha, []).append(pkg)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        prices_kg = [min(v) for _, v in sorted(prices_by_date.items())]

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
