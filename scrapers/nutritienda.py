"""
scrapers/nutritienda.py — Scraper para Nutritienda.com
Usa requests + BeautifulSoup (HTML server-side renderizado).
"""

import time
from bs4 import BeautifulSoup
from .base import hacer_peticion, producto_base

TIENDA = "Nutritienda"
DELAY  = 3

CATEGORIAS = [
    {"nombre": "Proteinas Whey", "url": "https://www.nutritienda.com/es/proteinas-suero-whey"},
    {"nombre": "Creatina",       "url": "https://www.nutritienda.com/es/creatina"},
    {"nombre": "BCAA",           "url": "https://www.nutritienda.com/es/bcaas"},
    {"nombre": "Pre-Entreno",    "url": "https://www.nutritienda.com/es/pre-entrenamiento"},
]


def scrape() -> list[dict]:
    print(f"\n{'='*50}")
    print(f"  Scraping: {TIENDA}")
    print(f"{'='*50}")

    productos = []

    for cat in CATEGORIAS:
        print(f"\n  Categoria: {cat['nombre']}")
        response = hacer_peticion(cat["url"])
        if not response:
            print(f"  Sin respuesta, saltando...")
            continue

        soup = BeautifulSoup(response.text, "lxml")
        items = soup.select("div.grid-info-wrapper")

        if not items:
            items_price = soup.find_all("span", class_="price")
            items = [p.parent.parent for p in items_price if p.parent]

        print(f"  Encontrados: {len(items)} productos")

        for item in items:
            try:
                precio_elem = item.select_one("span.price")
                nombre_elem = item.select_one("h3 a")
                if not nombre_elem:
                    continue

                nombre = nombre_elem.get_text(strip=True)
                precio = precio_elem.get_text(strip=True) if precio_elem else "N/A"

                marca = ""
                title = nombre_elem.get("title", "")
                if " - " in title:
                    marca = title.split(" - ")[-1].strip()

                href = nombre_elem.get("href", "")
                url = href if href.startswith("http") else "https://www.nutritienda.com" + href

                # Imagen: buscar en el contenedor padre (grid-item) o hermanos
                imagen_url = None
                contenedor = item.parent or item
                img = contenedor.select_one("img[src]")
                if img:
                    src = img.get("data-src") or img.get("src", "")
                    if src and "placeholder" not in src.lower() and src.startswith("http"):
                        imagen_url = src

                if nombre:
                    productos.append(producto_base(nombre, precio, marca, cat["nombre"], TIENDA, url, imagen_url))
            except Exception as e:
                print(f"  Error en producto: {e}")

        print(f"  Acumulado: {len(productos)}")
        time.sleep(DELAY)

    return productos
