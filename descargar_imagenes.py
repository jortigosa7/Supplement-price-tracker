"""
descargar_imagenes.py — Descarga y optimiza imágenes de productos para StackFit
================================================================================

Lee data/products.json, descarga las imágenes scrapeadas (o extrae og:image
como fallback), las redimensiona a 200x200 WebP y las guarda en docs/img/productos/.

Uso:
    python descargar_imagenes.py            # solo productos sin imagen local
    python descargar_imagenes.py --force    # redownload todas

Dependencias:
    pip install Pillow requests
"""

import io
import json
import os
import re
import sys
import time
import unicodedata
import argparse
import requests
from PIL import Image

DATA_DIR   = "data"
DOCS_DIR   = "docs"
IMG_DIR    = os.path.join(DOCS_DIR, "img", "productos")
PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")

IMG_SIZE   = (200, 200)
IMG_FORMAT = "WEBP"
IMG_QUALITY = 82

TIMEOUT = 12
DELAY   = 0.8  # segundos entre peticiones

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
}

# Placeholders SVG por categoría
PLACEHOLDERS = {
    "proteina-whey": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">
  <rect width="80" height="80" rx="8" fill="#f0f0f0"/>
  <text x="40" y="48" font-size="36" text-anchor="middle" fill="#c8ff4d">🥛</text>
</svg>""",
    "creatina": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">
  <rect width="80" height="80" rx="8" fill="#f0f0f0"/>
  <text x="40" y="48" font-size="36" text-anchor="middle" fill="#c8ff4d">⚡</text>
</svg>""",
    "bcaa": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">
  <rect width="80" height="80" rx="8" fill="#f0f0f0"/>
  <text x="40" y="48" font-size="36" text-anchor="middle" fill="#c8ff4d">💊</text>
</svg>""",
    "pre-entreno": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">
  <rect width="80" height="80" rx="8" fill="#f0f0f0"/>
  <text x="40" y="48" font-size="36" text-anchor="middle" fill="#c8ff4d">🔥</text>
</svg>""",
}


def slugify(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:80]


def img_path_for(producto_id: str) -> str:
    return os.path.join(IMG_DIR, f"{producto_id}.webp")


def img_web_path(producto_id: str) -> str:
    return f"/img/productos/{producto_id}.webp"


def descargar_imagen(url: str) -> Image.Image | None:
    """Descarga una URL de imagen y devuelve un objeto PIL Image, o None si falla."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
        if r.status_code != 200:
            return None
        content_type = r.headers.get("Content-Type", "")
        if "html" in content_type:
            return None
        img = Image.open(io.BytesIO(r.content))
        return img
    except Exception:
        return None


def extraer_og_image(producto_url: str) -> str | None:
    """Intenta obtener og:image de la página de producto como fallback."""
    try:
        r = requests.get(producto_url, headers={**HEADERS, "Accept": "text/html"}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        # Buscar og:image con regex simple (evita parsear todo el HTML)
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', r.text)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r.text)
        if m:
            url = m.group(1).strip()
            return url if url.startswith("http") else None
    except Exception:
        pass
    return None


def procesar_imagen(img: Image.Image) -> bytes:
    """Redimensiona a 200x200 (thumbnail con padding blanco) y convierte a WebP."""
    img = img.convert("RGBA")

    # Thumbnail manteniendo ratio
    img.thumbnail(IMG_SIZE, Image.LANCZOS)

    # Canvas blanco 200x200
    canvas = Image.new("RGBA", IMG_SIZE, (255, 255, 255, 255))
    offset = ((IMG_SIZE[0] - img.width) // 2, (IMG_SIZE[1] - img.height) // 2)
    canvas.paste(img, offset, img if img.mode == "RGBA" else None)

    # Convertir a RGB antes de guardar como WebP
    canvas_rgb = canvas.convert("RGB")
    buf = io.BytesIO()
    canvas_rgb.save(buf, format=IMG_FORMAT, quality=IMG_QUALITY, method=6)
    return buf.getvalue()


def generar_placeholders():
    """Genera SVG placeholders por categoría en docs/img/productos/."""
    ph_dir = IMG_DIR
    os.makedirs(ph_dir, exist_ok=True)
    for cat_slug, svg in PLACEHOLDERS.items():
        path = os.path.join(ph_dir, f"placeholder-{cat_slug}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    print(f"  ✓ Placeholders SVG generados en {ph_dir}/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Redownload todas las imágenes")
    args = parser.parse_args()

    os.makedirs(IMG_DIR, exist_ok=True)
    generar_placeholders()

    with open(PRODUCTS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    productos = data.get("products", [])
    total = len(productos)
    ok = 0
    fallback_og = 0
    sin_imagen = 0
    ya_existe = 0

    print(f"\n{'='*50}")
    print(f"  Descargando imágenes ({total} productos)")
    print(f"{'='*50}\n")

    for i, p in enumerate(productos):
        pid      = p["id"]
        cat      = p.get("categoria", "unknown")
        dest     = img_path_for(pid)

        if os.path.exists(dest) and not args.force:
            ya_existe += 1
            continue

        # URL de imagen del scraper (tienda más barata primero)
        imagen_url = p.get("imagen_url")
        if not imagen_url:
            for pr in p.get("precios", []):
                if pr.get("imagen_url"):
                    imagen_url = pr["imagen_url"]
                    break

        img = None
        if imagen_url:
            img = descargar_imagen(imagen_url)

        # Fallback: og:image de la URL del producto más barato
        if img is None:
            producto_url = (p.get("precios") or [{}])[0].get("url_afiliado", "")
            if producto_url and "hsn" not in producto_url and "prozis" not in producto_url:
                # Prozis y HSN suelen bloquear; intentamos con Nutritienda y MyProtein
                og = extraer_og_image(producto_url)
                if og:
                    img = descargar_imagen(og)
                    if img:
                        fallback_og += 1
                time.sleep(DELAY)

        if img is not None:
            try:
                webp_bytes = procesar_imagen(img)
                with open(dest, "wb") as f:
                    f.write(webp_bytes)
                ok += 1
            except Exception as e:
                print(f"  [ERROR] {p['nombre_normalizado'][:50]}: {e}")
                sin_imagen += 1
        else:
            sin_imagen += 1

        if (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{total} (ok={ok}, sin_img={sin_imagen}, cache={ya_existe})")

        time.sleep(DELAY)

    print(f"\n  Resultado:")
    print(f"    Descargadas:   {ok}")
    print(f"    Fallback og:   {fallback_og}")
    print(f"    Sin imagen:    {sin_imagen}")
    print(f"    Ya existían:   {ya_existe}")
    print(f"\n  Imágenes en: {IMG_DIR}/")


if __name__ == "__main__":
    main()
