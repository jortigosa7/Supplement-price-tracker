"""
matching.py — Sistema de matching cross-tienda
===============================================

Dado un listado plano de productos de múltiples tiendas, agrupa
los que representan el mismo producto bajo un único objeto con
un array precios[] por tienda.

Estrategia de matching (por orden de prioridad):
  1. Clave exacta: (categoria, marca_norm, peso_kg)
     → productos con misma marca y peso en la misma categoría son el mismo
  2. Nombre normalizado: si la clave exacta no matchea,
     comparar nombre token por token (overlap >= 60%)
  3. Sin match: cada producto queda como grupo independiente
"""

import re
import unicodedata
from limpieza import extraer_peso_kg

# Marcas conocidas para normalización
MARCAS_NORM = {
    "myprotein": "MyProtein",
    "my protein": "MyProtein",
    "hsn": "HSN",
    "hsnstore": "HSN",
    "prozis": "Prozis",
    "optimum nutrition": "Optimum Nutrition",
    "on ": "Optimum Nutrition",
    "gold standard": "Optimum Nutrition",
    "scitec": "Scitec Nutrition",
    "scitec nutrition": "Scitec Nutrition",
    "biotech": "BioTechUSA",
    "biotechusa": "BioTechUSA",
    "biotech usa": "BioTechUSA",
    "weider": "Weider",
    "amix": "Amix",
    "dymatize": "Dymatize",
    "bsn": "BSN",
    "muscletech": "MuscleTech",
    "muscle tech": "MuscleTech",
    "bulk": "Bulk",
    "bulkpowders": "Bulk",
    "quamtrax": "Quamtrax",
    "life pro": "Life Pro Nutrition",
    "life pro nutrition": "Life Pro Nutrition",
    "applied nutrition": "Applied Nutrition",
    "mutant": "Mutant",
    "usn": "USN",
}

# Keywords que identifican el tipo de producto dentro de la categoría
KEYWORDS_PRODUCTO = {
    "Proteinas Whey": ["concentrate", "isolate", "isolado", "concentrado", "whey gold", "100% whey", "pure whey"],
    "Creatina":       ["monohydrate", "monohidrato", "creapure", "hcl", "ethyl ester"],
    "BCAA":           ["2:1:1", "4:1:1", "8:1:1", "glutamine", "glutamina"],
    "Pre-Entreno":    ["abe", "c4", "no xplode"],
}


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin acentos, sin puntuación, espacios normalizados."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def extraer_marca_normalizada(nombre: str, marca_raw: str) -> str:
    """Devuelve la marca canónica o '' si no se reconoce."""
    texto = normalizar_texto(nombre + " " + marca_raw)
    for patron, marca_canon in MARCAS_NORM.items():
        if normalizar_texto(patron) in texto:
            return marca_canon
    return ""


def tokens(texto: str) -> set[str]:
    """Devuelve el conjunto de tokens relevantes (palabras >2 chars, sin stopwords)."""
    stopwords = {"de", "la", "el", "en", "con", "para", "y", "a", "e",
                 "los", "las", "del", "protein", "proteina", "whey", "g", "kg"}
    return {t for t in normalizar_texto(texto).split() if len(t) > 2 and t not in stopwords}


def similitud_nombres(nombre1: str, nombre2: str) -> float:
    """Jaccard similarity entre los tokens de dos nombres. [0.0 – 1.0]"""
    t1 = tokens(nombre1)
    t2 = tokens(nombre2)
    if not t1 or not t2:
        return 0.0
    interseccion = t1 & t2
    union = t1 | t2
    return len(interseccion) / len(union)


def clave_exacta(producto: dict) -> tuple | None:
    """
    Clave primaria de matching: (categoria, marca_normalizada, peso_kg_redondeado).
    Devuelve None si no hay suficientes datos para la clave.
    """
    marca = extraer_marca_normalizada(producto.get("nombre", ""), producto.get("marca", ""))
    peso  = producto.get("peso_kg")
    cat   = producto.get("categoria", "")

    if not marca or peso is None or peso <= 0:
        return None

    # Redondear peso al 0.1 más cercano para absorber diferencias "2kg" vs "2.0kg"
    peso_r = round(peso, 1)
    return (cat, marca, peso_r)


def agrupar_productos(productos_flat: list[dict]) -> list[dict]:
    """
    Recibe la lista plana de todos los scrapers y devuelve
    la lista agrupada con precios[] por tienda.

    Cada grupo tiene la estructura:
    {
        "nombre_normalizado": str,
        "categoria": str,
        "marca": str,
        "peso_kg": float | None,
        "precios": [ {"tienda": ..., "precio_eur": ..., "url_afiliado": ..., ...} ]
    }
    """
    from limpieza import limpiar_precio

    grupos: list[dict] = []

    for p in productos_flat:
        nombre    = p.get("nombre", "").strip()
        precio_str = p.get("precio", "N/A")
        tienda    = p.get("tienda", "?")
        url       = p.get("url", "#")
        fecha     = p.get("fecha_scraping", "")
        categoria = p.get("categoria", "")
        marca_raw = p.get("marca", "")

        precio_eur = limpiar_precio(precio_str)
        if not nombre or precio_eur is None:
            continue

        peso_kg = extraer_peso_kg(nombre)

        imagen_url = p.get("imagen_url")

        entrada_precio = {
            "tienda":        tienda,
            "precio_eur":    precio_eur,
            "url_afiliado":  url,
            "imagen_url":    imagen_url,
            "en_oferta":     False,
            "precio_original": None,
            "fecha":         fecha,
        }

        # 1. Intentar match por clave exacta en grupos existentes
        producto_tmp = {"nombre": nombre, "marca": marca_raw, "peso_kg": peso_kg, "categoria": categoria}
        clave = clave_exacta(producto_tmp)
        match_grupo = None

        if clave:
            for g in grupos:
                if clave_exacta({
                    "nombre":    g["nombre_normalizado"],
                    "marca":     g["marca"],
                    "peso_kg":   g["peso_kg"],
                    "categoria": g["categoria"],
                }) == clave:
                    # Verificar que la tienda no esté ya en este grupo
                    tiendas_existentes = {pr["tienda"] for pr in g["precios"]}
                    if tienda not in tiendas_existentes:
                        match_grupo = g
                        break

        # 2. Si no hay match exacto, buscar por similitud de nombre (umbral 0.65)
        if match_grupo is None:
            for g in grupos:
                if g["categoria"] != categoria:
                    continue
                sim = similitud_nombres(nombre, g["nombre_normalizado"])
                if sim >= 0.65:
                    tiendas_existentes = {pr["tienda"] for pr in g["precios"]}
                    if tienda not in tiendas_existentes:
                        match_grupo = g
                        break

        if match_grupo is not None:
            match_grupo["precios"].append(entrada_precio)
        else:
            # Nuevo grupo
            marca_canon = extraer_marca_normalizada(nombre, marca_raw)
            grupos.append({
                "nombre_normalizado": nombre,
                "categoria":         categoria,
                "marca":             marca_canon or marca_raw or "Desconocida",
                "peso_kg":           peso_kg,
                "precios":           [entrada_precio],
            })

    # Post-proceso: ordenar precios, calcular mínimos, elegir imagen
    for g in grupos:
        g["precios"].sort(key=lambda x: x["precio_eur"])
        mejor = g["precios"][0]
        g["precio_min"]        = mejor["precio_eur"]
        g["tienda_mas_barata"] = mejor["tienda"]
        g["precio_por_kg_min"] = (
            round(mejor["precio_eur"] / g["peso_kg"], 2)
            if g["peso_kg"] and g["peso_kg"] > 0 else None
        )
        # Imagen: usar la de la tienda más barata; si no tiene, la primera disponible
        g["imagen_url"] = mejor.get("imagen_url") or next(
            (pr["imagen_url"] for pr in g["precios"] if pr.get("imagen_url")), None
        )

    # Ordenar grupos: categoria + precio_por_kg
    grupos.sort(key=lambda g: (
        g["categoria"],
        g["precio_por_kg_min"] if g["precio_por_kg_min"] is not None else 9999
    ))

    return grupos
