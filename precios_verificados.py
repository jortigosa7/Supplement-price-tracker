"""
Precios verificados a mano que los checks anti-bug deben dejar pasar.

Los checks de build.py y checks.py marcan como error cualquier €/kg muy por debajo
de la mediana o cualquier caída brusca, porque así se manifestaba el bug del precio
"desde". En rebajas fuertes (Black Friday, flash sales) un precio real puede caer
igual de bajo. Para esos casos se añade una entrada a data/precios_verificados.json:

    {"id": "...", "tienda": "MyProtein", "precio": 12.0,
     "hasta": "2026-12-01", "nota": "Black Friday -83 %, comprobado en la web"}

Solo se acepta si coincide el ID, la tienda y el precio EXACTO, y hoy <= "hasta".
Si mañana el scraper devuelve otro precio raro para ese producto, los checks
vuelven a saltar con normalidad.
"""
import json
import os
from datetime import date

_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "precios_verificados.json")
_cache: list[dict] | None = None


def _cargar() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            with open(_RUTA, encoding="utf-8") as f:
                _cache = json.load(f)
        except FileNotFoundError:
            _cache = []
    return _cache


def es_precio_verificado(producto_id: str, tienda: str | None, precio) -> bool:
    if precio is None:
        return False
    hoy = date.today().isoformat()
    for e in _cargar():
        if e.get("id") != producto_id:
            continue
        if tienda is not None and e.get("tienda") != tienda:
            continue
        if abs(float(e.get("precio", -1)) - float(precio)) > 0.005:
            continue
        if e.get("hasta") and hoy > e["hasta"]:
            continue
        return True
    return False


def producto_verificado(p: dict) -> bool:
    """True si el precio mínimo actual del producto está verificado en alguna tienda."""
    pid = p.get("id", "")
    pmin = p.get("precio_min")
    if pmin is None:
        return False
    return any(
        es_precio_verificado(pid, pr.get("tienda"), pr.get("precio_eur"))
        and abs(float(pr.get("precio_eur") or -1) - float(pmin)) <= 0.005
        for pr in p.get("precios", [])
    )
