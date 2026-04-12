"""
scrapers/base.py — Utilidades compartidas por todos los scrapers
"""

import re
import time
import requests
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

TODAY = datetime.now().strftime("%Y-%m-%d")


def hacer_peticion(url: str, max_reintentos: int = 3, delay: int = 2) -> requests.Response | None:
    for intento in range(max_reintentos):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                print(f"   Rate limited, esperando 15s...")
                time.sleep(15)
            else:
                print(f"   HTTP {r.status_code} para {url}")
        except requests.exceptions.Timeout:
            print(f"   Timeout (intento {intento+1}/{max_reintentos})")
        except requests.exceptions.ConnectionError:
            print(f"   Error de conexion (intento {intento+1}/{max_reintentos})")
        except requests.exceptions.RequestException as e:
            print(f"   Error: {e}")
            return None
        if intento < max_reintentos - 1:
            time.sleep(delay)
    return None


def producto_base(nombre, precio_str, marca, categoria, tienda, url, imagen_url=None) -> dict:
    """Schema plano compartido por todos los scrapers."""
    return {
        "nombre":         nombre.strip(),
        "precio":         precio_str.strip() if precio_str else "N/A",
        "marca":          marca.strip() if marca else "",
        "categoria":      categoria,
        "tienda":         tienda,
        "url":            url,
        "imagen_url":     imagen_url or None,
        "fecha_scraping": TODAY,
    }
