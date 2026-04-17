"""
scrapers/detail_cache.py — Caché de 7 días para páginas de detalle

Guarda el HTML de cada página de detalle en cache/detail/{store}/{md5}.html
y lo reutiliza durante 7 días. Evita re-scrapear páginas cuyo precio no cambió.

Uso:
    from scrapers.detail_cache import get_cached, save_cache

    html = get_cached('hsn', url)
    if html is None:
        r = hacer_peticion(url)
        html = r.text
        save_cache('hsn', url, html)
"""

import hashlib
import os
import time

CACHE_DIR = "cache/detail"
CACHE_TTL_DAYS = 7


def _cache_path(store: str, url: str) -> str:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, store, f"{h}.html")


def get_cached(store: str, url: str) -> str | None:
    """Devuelve el HTML cacheado si existe y tiene menos de 7 días. Si no, None."""
    path = _cache_path(store, url)
    if not os.path.exists(path):
        return None
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days >= CACHE_TTL_DAYS:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def save_cache(store: str, url: str, html: str) -> None:
    """Guarda el HTML en caché para la URL dada."""
    path = _cache_path(store, url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
