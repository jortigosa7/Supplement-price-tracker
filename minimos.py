"""
Detección de mínimos reales de precio.

Un producto está en "mínimo real" cuando hoy cuesta lo mismo o menos que en todo
su historial reciente, bastante menos de lo que suele costar, y además casi nunca
ha estado tan barato. Las tres condiciones hacen falta juntas: las tiendas de
suplementos encadenan códigos de descuento, así que "está rebajado" no dice nada.

Solo se compara un producto consigo mismo: mismo ID (mismo formato) y misma tienda,
en euros. Nunca se mezclan botes de distinto peso.

Lo usan build.py (página /ofertas/ y data/minimos.json) y avisos_telegram.py.
"""

import math
import statistics
from datetime import date, timedelta

VENTANA_DIAS = 90             # historial que se mira hacia atrás
MIN_FECHAS = 8                # observaciones mínimas para fiarse del historial
MIN_DIAS_HISTORIAL = 30       # días mínimos entre la primera observación y hoy
MIN_REBAJA = 0.07             # al menos un 7 % por debajo del precio habitual (mediana)
MAX_FRECUENCIA = 0.25         # como mucho el 25 % de las veces ha estado así de barato
MAX_CAIDA = 0.50              # una caída mayor del 50 % se trata como error de scraping
PRECIO_MINIMO_EUR = 8.0       # por debajo de esto (sobres, muestras) no merece aviso
PESO_MINIMO_KG = 0.15         # mismo corte que _excluir_producto en build.py
TOLERANCIA = 0.005            # medio céntimo: iguala el mínimo aunque baile el redondeo


def _serie_previa(entradas: list[dict], tienda: str, fecha_hoy: str) -> list[tuple[str, float]]:
    """Un precio por fecha (el más bajo), de la tienda dada, dentro de la ventana y antes de hoy."""
    corte = (date.fromisoformat(fecha_hoy) - timedelta(days=VENTANA_DIAS)).isoformat()
    por_fecha: dict[str, float] = {}
    for e in entradas:
        fecha = e.get("fecha", "")
        precio = e.get("precio")
        if e.get("tienda") != tienda or precio is None or not (corte <= fecha < fecha_hoy):
            continue
        por_fecha[fecha] = min(float(precio), por_fecha.get(fecha, float(precio)))
    return sorted(por_fecha.items())


def evaluar_precio(precio_hoy: float, serie: list[tuple[str, float]], fecha_hoy: str) -> dict | None:
    """
    Decide si precio_hoy es un mínimo real frente a la serie previa [(fecha, precio), ...].
    Devuelve las cifras del aviso, o None si no lo es.
    """
    if len(serie) < MIN_FECHAS:
        return None
    hoy = date.fromisoformat(fecha_hoy)
    dias_historial = (hoy - date.fromisoformat(serie[0][0])).days
    if dias_historial < MIN_DIAS_HISTORIAL:
        return None

    valores = [v for _, v in serie]
    minimo_previo = min(valores)
    habitual = statistics.median(valores)
    ultimo = valores[-1]

    if precio_hoy > minimo_previo + TOLERANCIA:
        return None                                   # ya ha estado más barato
    if precio_hoy > habitual * (1 - MIN_REBAJA):
        return None                                   # no está lejos de su precio habitual
    if precio_hoy < ultimo * (1 - MAX_CAIDA) or precio_hoy < habitual * (1 - MAX_CAIDA):
        return None                                   # caída imposible: variante equivocada
    veces_asi = sum(1 for v in valores if v <= precio_hoy * 1.01)
    if veces_asi / len(valores) > MAX_FRECUENCIA:
        return None                                   # suele estar a este precio: no es noticia

    # Desde cuándo está a este precio (racha de observaciones seguidas igual o más baratas)
    desde = fecha_hoy
    antes_de_racha = list(valores)
    for fecha, valor in reversed(serie):
        if valor > precio_hoy + TOLERANCIA:
            break
        desde = fecha
        antes_de_racha.pop()
    # Récord = nunca había estado tan barato antes de esta bajada (si no, iguala un mínimo anterior)
    minimo_anterior = min(antes_de_racha) if antes_de_racha else minimo_previo

    return {
        "precio":          round(precio_hoy, 2),
        "precio_habitual": round(habitual, 2),
        "minimo_anterior": round(minimo_anterior, 2),
        "rebaja_pct":      round((habitual - precio_hoy) / habitual * 100, 1),
        "es_record":       precio_hoy < minimo_anterior - TOLERANCIA,
        "dias_historial":  min(dias_historial, VENTANA_DIAS),
        "n_fechas":        len(serie),
        "desde":           desde,
    }


def detectar_minimos(productos_web: list[dict], hist_by_id: dict, tiendas_afiliadas: set[str],
                     ids_excluidos: set[str] | None = None) -> list[dict]:
    """
    Productos que hoy están en mínimo real en una tienda afiliada, ordenados por
    interés (rebaja frente al precio habitual, ponderada por popularidad).

    Solo cuenta si la tienda afiliada es además la más barata para ese producto:
    avisar de un "mínimo" cuando otra tienda lo vende por menos sería engañar.
    """
    ids_excluidos = ids_excluidos or set()

    # Fecha del último scrape de cada tienda: un precio de un scrape anterior no es "hoy"
    fecha_tienda: dict[str, str] = {}
    for p in productos_web:
        for pr in p.get("precios", []):
            f = pr.get("fecha") or ""
            if f > fecha_tienda.get(pr.get("tienda"), ""):
                fecha_tienda[pr["tienda"]] = f

    minimos = []
    for p in productos_web:
        tienda = p.get("tienda_mas_barata")
        if tienda not in tiendas_afiliadas or p["id"] in ids_excluidos:
            continue
        if p.get("agotado") or p.get("sin_precio"):
            continue
        if (p.get("peso_kg") or 0) < PESO_MINIMO_KG:
            continue
        pr = next((x for x in p.get("precios", []) if x.get("tienda") == tienda), None)
        if not pr or pr.get("agotado") or pr.get("sin_precio") or not pr.get("url_afiliado"):
            continue
        precio_hoy = pr.get("precio_eur")
        fecha_hoy = pr.get("fecha")
        if not precio_hoy or precio_hoy < PRECIO_MINIMO_EUR or not fecha_hoy:
            continue
        if fecha_hoy != fecha_tienda.get(tienda):
            continue

        serie = _serie_previa(hist_by_id.get(p["id"], []), tienda, fecha_hoy)
        cifras = evaluar_precio(float(precio_hoy), serie, fecha_hoy)
        if not cifras:
            continue

        valoraciones = int(p.get("store_rating_count") or 0)
        minimos.append({
            "id":            p["id"],
            "nombre":        p.get("nombre_display") or p.get("nombre_normalizado"),
            "categoria":     p.get("categoria"),
            "tienda":        tienda,
            "fecha":         fecha_hoy,
            "peso_kg":       p.get("peso_kg"),
            "precio_por_kg": p.get("precio_por_kg_min"),
            "valoraciones":  valoraciones,
            "url_afiliado":  pr["url_afiliado"],
            "pagina_url":    p.get("pagina_url"),
            # Rebaja ponderada por popularidad: un -27 % en una whey con 900 valoraciones
            # interesa a más gente que un -40 % en un producto que casi nadie compra.
            "interes":       round(cifras["rebaja_pct"] * math.log10(10 + valoraciones), 1),
            **cifras,
        })

    minimos.sort(key=lambda m: (-m["interes"], m["id"]))
    return minimos
