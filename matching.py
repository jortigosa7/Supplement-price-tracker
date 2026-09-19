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

import math
import re
import unicodedata
from limpieza import extraer_peso_kg


def _peso_valido(peso) -> float | None:
    """Devuelve el peso como float si es un número positivo finito; None en otro caso."""
    try:
        f = float(peso)
        return f if math.isfinite(f) and f > 0 else None
    except (TypeError, ValueError):
        return None

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
    "keepgoing": "KeepGoing",
}

# Tokens que impiden el match si están en un nombre pero no en el otro.
# Un qualifier asimétrico indica que son productos distintos aunque el nombre sea similar.
QUALIFIER_TOKENS = frozenset({
    # Tipo de proteína (no mezclar vegetal con animal)
    "vegan", "vegetal",
    # Variante sin edulcorantes (formulación distinta al edulcorado)
    "edulcorantes",         # de "sin edulcorantes"
    # Forma de proteína (no mezclar isolate con concentrate ni hidrolizado)
    "isolate", "aislado", "isolado",
    "hidrolizado", "hidrolizada", "hydrolyzed",
    "hydro",                # ej. "Hydro Whey" vs "Whey"
    # Caseína vs whey (subtipo distinto)
    "caseina",
    # Formato sólido vs polvo (no mezclar)
    "capsulas", "comprimidos", "tabletas", "gummies",
})


def _tiene_qualifier(q: str, token_set: set[str]) -> bool:
    """
    Comprueba si el qualifier está en el conjunto de tokens, exacto o como subcadena.
    Necesario para capturar composiciones como "evohydro" → contiene "hydro".
    """
    return q in token_set or any(q in t for t in token_set)


def qualifiers_compatibles(nombre1: str, nombre2: str) -> bool:
    """
    Devuelve False si un qualifier está en uno de los nombres pero no en el otro.
    Evita agrupar, por ejemplo, una proteína vegetal con una whey o un isolate
    con un concentrate aunque la similitud Jaccard sea alta.
    """
    t1 = tokens(nombre1)
    t2 = tokens(nombre2)
    for q in QUALIFIER_TOKENS:
        if _tiene_qualifier(q, t1) != _tiene_qualifier(q, t2):
            return False

    # Regla 4: formato dosificado (Xmg por toma) identifica un producto en cápsulas o
    # sobres dosificados, no polvo a granel. Si un nombre tiene dosis en mg y el otro no,
    # son productos distintos aunque el nombre base sea similar.
    _dosis_mg = re.compile(r'\b\d+\s*mg\b', re.IGNORECASE)
    if bool(_dosis_mg.search(nombre1)) != bool(_dosis_mg.search(nombre2)):
        return False

    # Los ratios de BCAA (2:1:1, 4:1:1, 8:1:1…) se pierden en tokens() porque los
    # dígitos individuales tienen len ≤ 2 y se filtran. Y normalizar_texto elimina
    # los ":" por lo que hay que buscar el ratio en el texto original.
    _ratio = re.compile(r"\d+\s*:\s*\d+\s*:\s*\d+")
    r1 = _ratio.search(nombre1)
    r2 = _ratio.search(nombre2)
    # Normalizar el ratio encontrado (quitar espacios) para comparar "4 : 1 : 1" == "4:1:1"
    ratio_str1 = re.sub(r"\s", "", r1.group()) if r1 else None
    ratio_str2 = re.sub(r"\s", "", r2.group()) if r2 else None
    if ratio_str1 != ratio_str2:
        return False

    return True


# Tokens genéricos por categoría: presentes en casi todo producto de la categoría.
# Si la intersección de tokens entre dos nombres se reduce solo a estos, el match
# es demasiado vago y se rechaza (regla 3).
_GENERICOS_CAT = {
    "bcaa":     frozenset({"bcaa"}),
    "creatina": frozenset({"creatina", "creatine"}),  # español e inglés
    "pre":      frozenset({"pre", "workout", "entreno", "entrenamiento", "preworkout"}),
}


def _tokens_suficientes(interseccion: set[str], categoria: str) -> bool:
    """
    Devuelve False si la intersección solo contiene palabras genéricas de la categoría.
    Regla 3: un match basado únicamente en el nombre de la categoría no es válido.
    """
    cat = normalizar_texto(categoria)
    genericos: frozenset[str] = frozenset()
    if "bcaa" in cat:
        genericos = _GENERICOS_CAT["bcaa"]
    elif "creatina" in cat:
        genericos = _GENERICOS_CAT["creatina"]
    elif "pre" in cat and any(x in cat for x in ("entreno", "workout")):
        genericos = _GENERICOS_CAT["pre"]
    return bool(interseccion - genericos)


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


def normalizar_marca_final(marca: str) -> str:
    """
    Normaliza la capitalización de una marca ya extraída aplicando MARCAS_NORM.
    Punto de entrada único para corregir variantes de capitalización (ej. 'Myprotein'
    → 'MyProtein', 'Keepgoing' → 'KeepGoing') sin tocar los scrapers.
    Se llama desde build.py como último paso tras corregir_marcas().
    """
    if not marca:
        return marca
    canon = extraer_marca_normalizada("", marca)
    return canon if canon else marca.strip()


def extraer_marca_normalizada(nombre: str, marca_raw: str) -> str:
    """Devuelve la marca canónica o '' si no se reconoce."""
    texto = normalizar_texto(nombre + " " + marca_raw)
    for patron, marca_canon in MARCAS_NORM.items():
        patron_norm = normalizar_texto(patron)
        # Usar word boundary para evitar falsos positivos: "on" no debe
        # coincidir dentro de "desconocida" ni dentro de "con" (preposición).
        if re.search(r"\b" + re.escape(patron_norm) + r"\b", texto):
            return marca_canon
    return ""


def tokens(texto: str) -> set[str]:
    """
    Devuelve el conjunto de tokens relevantes (palabras >2 chars, sin stopwords).
    Las expresiones de peso ("300 g", "2 Kg", "0,3 l"…) se eliminan antes de
    tokenizar: el peso se compara numéricamente vía peso_kg, no por texto.
    """
    stopwords = {"de", "la", "el", "en", "con", "para", "y", "a", "e",
                 "los", "las", "del", "protein", "proteina", "whey", "g", "kg",
                 "the"}  # artículo inglés: no aporta nada al matching
    # Eliminar expresiones numéricas de peso/volumen: "300g", "300 g", "2 Kg",
    # "0.3 kg", "2,27kg", "1000ml", "1 l", etc. El \b evita falsos positivos
    # en palabras como "Gold" (que empieza por "g").
    texto_sin_peso = re.sub(
        r'\d+[\d.,]*\s*(?:kg|g|ml|l)\b', '', texto, flags=re.IGNORECASE
    )
    # Extraer ratios BCAA antes de normalizar: "2:1:1", "4 : 1 : 1" → token "2:1:1".
    # normalizar_texto elimina los ":" y deja dígitos sueltos (len ≤ 2 → filtrados).
    ratios = {re.sub(r'\s', '', m) for m in re.findall(r'\d+\s*:\s*\d+\s*:\s*\d+', texto_sin_peso)}
    base = {t for t in normalizar_texto(texto_sin_peso).split() if len(t) > 2 and t not in stopwords}
    return base | ratios


def similitud_nombres(nombre1: str, nombre2: str,
                       peso_kg1: float | None = None,
                       peso_kg2: float | None = None) -> float:
    """
    Jaccard similarity entre los tokens de dos nombres. [0.0 – 1.0]
    Si se proporcionan ambos pesos y difieren >15%, devuelve 0.0:
    mismo nombre en distinto formato (300g vs 500g) → productos distintos.
    """
    if peso_kg1 and peso_kg2 and peso_kg1 > 0 and peso_kg2 > 0:
        if abs(peso_kg1 - peso_kg2) / max(peso_kg1, peso_kg2) > 0.15:
            return 0.0
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

    peso_f = _peso_valido(peso)
    if not marca or peso_f is None:
        return None

    # Redondear peso al 0.1 más cercano para absorber diferencias "2kg" vs "2.0kg"
    peso_r = round(peso_f, 1)
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
    avisos_ratio: list[str] = []  # Regla 2: pares rechazados por ratio de precio

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
            "_peso_kg":      peso_kg,  # peso del producto de esta entrada concreta
            # True cuando el precio es de lista (no de la opción concreta de HSN):
            # en ese caso precio y peso pueden ser de formatos distintos → €/kg = None
            "_precio_sin_confirmar": p.get("_precio_sin_confirmar", False),
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
                        # Aplicar qualifiers también en clave exacta: dos productos del
                        # mismo brand y peso pueden ser formulaciones distintas
                        # (ej. BCAA 2:1:1 vs 4:1:1 de la misma marca a 250g)
                        if not qualifiers_compatibles(nombre, g["nombre_normalizado"]):
                            continue
                        # Requerir tokens comunes suficientes: mismo brand+peso no basta
                        # si los nombres comparten solo el nombre de la categoría
                        # (p.ej. Evowhey vs Evopept, o Impact Creatine vs THE Creatine)
                        interseccion = tokens(nombre) & tokens(g["nombre_normalizado"])
                        if not _tokens_suficientes(interseccion, categoria):
                            continue
                        match_grupo = g
                        break

        # 2. Si no hay match exacto, buscar por similitud de nombre (umbral 0.65)
        if match_grupo is None:
            peso_v = _peso_valido(peso_kg)
            for g in grupos:
                if g["categoria"] != categoria:
                    continue

                # Regla 1: sin peso no agrupa con con peso (y viceversa)
                peso_g_v = _peso_valido(g.get("peso_kg"))
                if (peso_v is None) != (peso_g_v is None):
                    continue

                sim = similitud_nombres(nombre, g["nombre_normalizado"],
                                        peso_kg, g.get("peso_kg"))
                if sim < 0.65:
                    continue
                if not qualifiers_compatibles(nombre, g["nombre_normalizado"]):
                    continue

                # Regla 3: la intersección no puede ser solo tokens genéricos de la categoría
                interseccion = tokens(nombre) & tokens(g["nombre_normalizado"])
                if not _tokens_suficientes(interseccion, categoria):
                    continue

                tiendas_existentes = {pr["tienda"] for pr in g["precios"]}
                if tienda in tiendas_existentes:
                    continue

                # Regla 2: si precios difieren >2.5x con peso conocido en ambos, no es el mismo producto
                if peso_v is not None and peso_g_v is not None:
                    precio_g_min = min(pr["precio_eur"] for pr in g["precios"])
                    ratio = max(precio_eur, precio_g_min) / min(precio_eur, precio_g_min)
                    if ratio > 2.5:
                        avisos_ratio.append(
                            f"  [{categoria}] '{nombre}' {precio_eur:.2f}€ vs "
                            f"'{g['nombre_normalizado']}' {precio_g_min:.2f}€ "
                            f"(ratio {ratio:.1f}x) — no agrupado"
                        )
                        continue

                match_grupo = g
                break

        if match_grupo is not None:
            match_grupo["precios"].append(entrada_precio)
            # Si el grupo no tiene marca resuelta, actualizar con la del producto actual
            if not match_grupo["marca"] or match_grupo["marca"] == "Desconocida":
                marca_nueva = extraer_marca_normalizada(nombre, marca_raw)
                if marca_nueva:
                    match_grupo["marca"] = marca_nueva
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

        # Precio/kg: usa el peso de la MISMA entrada que tiene el precio más bajo.
        # Si el precio no está confirmado para ese formato (precio de lista en vez
        # del optionPrice de HSN), o si los pesos difieren >15%, €/kg = None.
        peso_mejor = mejor.get("_peso_kg")
        peso_grupo = g.get("peso_kg")
        if mejor.get("_precio_sin_confirmar"):
            # Precio de lista: no sabemos a qué formato corresponde → no dividir
            g["precio_por_kg_min"] = None
        elif peso_mejor and peso_mejor > 0:
            # Pesos distintos en más de un 15%: inconsistencia precio/formato
            if peso_grupo and abs(peso_mejor - peso_grupo) / max(peso_mejor, peso_grupo) > 0.15:
                g["precio_por_kg_min"] = None
            else:
                g["precio_por_kg_min"] = round(mejor["precio_eur"] / peso_mejor, 2)
        elif peso_grupo and peso_grupo > 0:
            g["precio_por_kg_min"] = round(mejor["precio_eur"] / peso_grupo, 2)
        else:
            g["precio_por_kg_min"] = None

        # Eliminar _peso_kg (solo interno); _precio_sin_confirmar se elimina en build.py
        # DESPUÉS de guardar_price_history para que pueda filtrar entradas inválidas.
        for pr in g["precios"]:
            pr.pop("_peso_kg", None)

        # Imagen: usar la de la tienda más barata; si no tiene, la primera disponible
        g["imagen_url"] = mejor.get("imagen_url") or next(
            (pr["imagen_url"] for pr in g["precios"] if pr.get("imagen_url")), None
        )

    # Informe de pares rechazados por ratio de precio (regla 2)
    if avisos_ratio:
        print(f"\n  AVISO matching — {len(avisos_ratio)} par(es) rechazados por ratio de precio >2.5x:")
        for aviso in avisos_ratio:
            print(aviso)

    # Ordenar grupos: categoria + precio_por_kg
    grupos.sort(key=lambda g: (
        g["categoria"],
        g["precio_por_kg_min"] if g["precio_por_kg_min"] is not None else 9999
    ))

    return grupos
