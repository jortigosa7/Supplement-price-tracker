"""
Verificación de aceptación de las páginas de producto de StackFit.

Se ejecuta DESPUÉS de build.py, sobre docs/ ya generado:
    python tests/verificar_paginas_producto.py

Sale con código 1 si algo falla. No modifica nada.
"""
import collections
import glob
import html
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS = "docs"
DATA = "data"
CATS = ("proteina-whey", "proteina-vegana", "creatina", "bcaa", "pre-entreno")
EXCLUIDOS = ("caldo", "claras-de-huevo", "huevo-entero", "texturizada")
VEGANO_KW = r"guisante|soja|arroz|calabaza|garbanzo|vegan|plant|cáñamo|canamo"
ANIMAL_KW = r"whey|suero|case[ií]n|huevo|alb[uú]mina|carne|beef|leche"
INGREDIENTES = {
    "taurina": r"taurina",
    "beta-alanina": r"beta.?alanina",
    "citrulina": r"citrulina",
    "arginina": r"arginina",
    "ribosa": r"ribosa",
    "glicerol": r"glicerol|glycopump",
}
PESO_EN_SLUG = re.compile(r"(?:^|-)\d+(?:-\d+)?(?:g|kg)(?:-|$)")
PESO_FINAL = re.compile(r"\d+(?:,\d+)?\s?(?:g|kg)$")
MINUSCULAS_OK = {"de", "del", "en", "y", "con", "sin", "edulcorantes", "polvo", "mesh", "la", "el", "a", "g", "kg"}
FILA_ALT = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2}) (€/kg prot\.|€/kg)(?: ([+−-])(\d+,\d) %)?")

fallos = collections.defaultdict(list)


def leer(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def es_redirect(h):
    return 'http-equiv="refresh"' in h[:3000]


def texto(h):
    b = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", h, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b))).strip()


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def tramo(t, desde, hasta_opciones):
    i = t.find(desde)
    if i < 0:
        return ""
    fin = len(t)
    for h in hasta_opciones:
        j = t.find(h, i + len(desde))
        if 0 < j < fin:
            fin = j
    return t[i:fin]


def hrefs(h):
    abs_ = re.findall(r'href="https://stackfit\.es(/[^"#?]*)"', h)
    rel = re.findall(r'href="(/[^"#?/][^"#?]*)"', h)
    return set(abs_) | set(rel)


nombres_cortos = json.load(open(os.path.join(DATA, "nombres_cortos.json"), encoding="utf-8"))

# ── Páginas de producto ──────────────────────────────────────────────
productos = {}  # url -> (cat, slug, html, texto)
for f in glob.glob(f"{DOCS}/*/*/index.html"):
    partes = os.path.normpath(f).split(os.sep)
    cat, slug = partes[-3], partes[-2]
    if cat not in CATS:
        continue
    h = leer(f)
    if es_redirect(h):
        continue
    productos[f"/{cat}/{slug}/"] = (cat, slug, h, texto(h))

if not productos:
    print("No hay páginas de producto en docs/. ¿Has ejecutado build.py?")
    sys.exit(1)

variantes_mal = {}
for v in nombres_cortos.values():
    sc = v[0] + v[1:].lower()
    if sc != v and len(v) > 8:
        variantes_mal[sc] = v

for url, (cat, slug, h, t) in sorted(productos.items()):
    title = html.unescape(re.search(r"<title>(.*?)</title>", h, re.S).group(1).strip())
    meta = html.unescape((re.search(r'<meta name="description" content="([^"]*)"', h) or [None, ""])[1])

    # Excluidos
    if any(k in slug for k in EXCLUIDOS):
        fallos["Producto excluido con página"].append(url)

    # URL estable: sin peso ni formato, para que no cambie cuando la tienda cambia el formato más barato
    if PESO_EN_SLUG.search(slug):
        fallos["URL de producto con peso/formato (cambia cuando cambia el formato)"].append(url)

    # Nombre corto (clave = slug de la URL) y título
    nc = nombres_cortos.get(slug)
    if not nc:
        fallos["Sin entrada en nombres_cortos.json"].append(slug)
    else:
        problemas = []
        if PESO_FINAL.search(nc):
            problemas.append("lleva peso")
        if re.search(r"[()®™]", nc):
            problemas.append("paréntesis o ®/™")
        if len(nc) > 40:
            problemas.append(f"{len(nc)} caracteres")
        minus = [w for w in re.split(r"[\s/]+", nc) if w and w[0].isalpha() and w[0].islower() and w not in MINUSCULAS_OK]
        if minus:
            problemas.append("minúsculas en " + ", ".join(minus))
        if problemas:
            fallos["Nombre corto mal formado (sin peso, sin paréntesis, ≤40, marca y línea en mayúscula)"].append(
                f"{slug} → '{nc}': {'; '.join(problemas)}")
    m = re.match(r"^(?P<n>.+?)(?: \d+(?:,\d+)? (?:g|kg))? \((?P<b>[^)]+)\): (precio hoy, )?€/kg y opiniones$", title)
    if not m:
        fallos["Título fuera de formato '{nombre} [formato] ({marca}): [precio hoy, ]€/kg y opiniones'"].append(f"{url} → {title}")
    elif nc and m.group("n") != nc:
        fallos["Título no usa el nombre corto"].append(f"{url} → '{m.group('n')}' ≠ '{nc}'")
    if "€/kg" not in meta or "/5 con" not in meta:
        fallos["Meta description sin €/kg o sin valoración"].append(f"{url} → {meta[:90]}")

    # Nombres en minúscula de nombre_display (alternativas, comparativas...)
    for mal, bien in variantes_mal.items():
        if mal in t:
            fallos["Nombre sin mayúsculas de marca (usa nombres_cortos)"].append(f"{url}: '{mal}' → '{bien}'")
            break

    # Secciones obligatorias
    if "Evolución del precio" not in t:
        fallos["Sin gráfico de historial"].append(url)
    if "Fuente:" not in t or "valoraciones" not in t:
        fallos["Sin sección de opiniones"].append(url)

    # Veredicto
    ver = tramo(t, "Hoy cuesta", ["Evolución del precio", "Ficha", "Posición en el ranking"])
    mp = re.search(r"Hoy cuesta (\d{1,3}(?:\.\d{3})*,\d{2}) €", ver)
    if not mp:
        fallos["Veredicto ausente o sin 'Hoy cuesta X €'"].append(url)
    else:
        if "€/kg" in ver:
            fallos["Veredicto mezcla € y €/kg"].append(f"{url} → {ver[:120]}")
        precio = num(mp.group(1))
        md = re.search(r"mediana 90 días: (\d{1,3}(?:\.\d{3})*,\d{2}) €", ver)
        mn = re.search(r"Mínimo: (\d{1,3}(?:\.\d{3})*,\d{2}) €", ver)
        if md:
            mediana = num(md.group(1))
            pct = re.search(r"un (\d+,\d) % (por debajo|por encima)", ver)
            if pct:
                real = abs(precio - mediana) / mediana * 100
                if abs(real - num(pct.group(1))) > 0.15:
                    fallos["% del veredicto mal calculado"].append(f"{url} → dice {pct.group(1)} %, real {real:.1f} %")
            if mn and num(mn.group(1)) == mediana == precio:
                fallos["Precio plano sin 'No ha cambiado de precio'"].append(url)
        elif "No ha cambiado de precio" not in ver:
            fallos["Veredicto sin mediana ni 'No ha cambiado'"].append(url)

    # Alternativas
    ini = max(t.find("Fuente:"), t.find("Posición en el ranking"), 0)
    ma = re.compile(r"\b(Otras|Otros|Más|Alternativas) ").search(t, ini)
    alt = tramo(t[ma.start():], ma.group(0), ["Comparativas", "Comparaciones", "Stack Fit Comparador"]) if ma else ""
    filas = FILA_ALT.findall(alt)
    if not filas:
        fallos["Sin alternativas"].append(url)
    else:
        unidades = {u for _, u, _, _ in filas}
        if len(unidades) > 1:
            fallos["Alternativas mezclan €/kg y €/kg prot."].append(url)
        vals = [num(v) for v, _, _, _ in filas]
        if vals != sorted(vals):
            fallos["Alternativas no ordenadas de menor a mayor"].append(f"{url} → {vals}")
        if any(not p for _, _, _, p in filas):
            fallos["Alternativa sin % de diferencia (o sin coma decimal)"].append(url)
        trozos = FILA_ALT.split(alt)[0::5]
        nombres_alt = " | ".join(trozos)
        if cat == "proteina-whey" and re.search(VEGANO_KW, nombres_alt, re.I) and "otro tipo" not in alt:
            fallos["Whey con alternativas veganas"].append(url)
        if cat == "proteina-vegana" and re.search(ANIMAL_KW, nombres_alt, re.I) and "otro tipo" not in alt:
            fallos["Vegana con alternativas animales"].append(url)
        if cat == "pre-entreno":
            for ing, rx in INGREDIENTES.items():
                if re.search(rx, slug.replace("-", " "), re.I):
                    otros = [n for n in trozos[:len(filas)] if n.strip() and not re.search(rx, n, re.I)]
                    if otros and "otro tipo" not in alt:
                        fallos["Pre-entreno con alternativas de otro ingrediente"].append(f"{url} ({ing})")
                    break
        if "clear" in slug and cat != "proteina-vegana" and "clear" not in alt.lower():
            fallos["Clear whey sin alternativas clear"].append(url)

    # Posición
    pos = tramo(t, "Posición en el ranking", ["Valoración", "Otras ", "Comparativas"])
    if "ingrediente único" in pos:
        fallos["Posición agrupa ingredientes distintos"].append(url)
    if filas and filas[0][1] == "€/kg prot." and pos and "proteína" not in pos:
        fallos["Posición por €/kg cuando la página compara por €/kg de proteína"].append(f"{url} → {pos[:100]}")

# Evobasic tiene que mostrar posición (es la página con más tráfico)
evo = [u for u in productos if "evobasic-whey" in u]
if evo and "Posición en el ranking" not in productos[evo[0]][3]:
    fallos["Evobasic Whey sin texto de posición"].append(evo[0])

# ── Enlazado y URLs en todo el sitio ────────────────────────────────
todas = glob.glob(f"{DOCS}/**/index.html", recursive=True)
entrantes = collections.Counter()
rotos = collections.Counter()
titulos = collections.defaultdict(list)
for f in todas:
    h = leer(f)
    yo = "/" + os.path.relpath(f, DOCS).replace(os.sep, "/").replace("index.html", "")
    if not es_redirect(h):
        tt = re.search(r"<title>(.*?)</title>", h, re.S)
        if tt:
            titulos[tt.group(1).strip()].append(yo)
    for l in hrefs(h):
        if l.endswith("/") and l != "/" and not os.path.exists(os.path.join(DOCS, l.strip("/"), "index.html")):
            rotos[l] += 1
        if l in productos and l != yo:
            entrantes[l] += 1

for l, n in rotos.items():
    fallos["Enlace interno roto"].append(f"{l} ({n} veces)")
for t, us in titulos.items():
    if len(us) > 1:
        fallos["Título duplicado"].append(f"{t} → {us[:3]}")
for url, (cat, slug, h, t) in productos.items():
    if not entrantes[url]:
        fallos["Producto sin enlaces entrantes"].append(url)
    if url not in hrefs(leer(f"{DOCS}/{cat}/index.html")):
        fallos["Producto no enlazado desde su categoría"].append(url)

# Cada comparación que aparece en una página de producto tiene que enlazar de vuelta a esa página
for url, (cat, slug, h, t) in productos.items():
    for l in hrefs(h):
        if l.startswith("/comparar/") and l != "/comparar/":
            fc = os.path.join(DOCS, l.strip("/"), "index.html")
            if os.path.exists(fc) and not es_redirect(leer(fc)) and url not in hrefs(leer(fc)):
                fallos["Comparación sin enlace a la página de producto"].append(f"{l} → {url}")

# Redirecciones históricas intactas
for fichero, base in (("slugs_historicos.json", "comparar"), ("slugs_producto_historicos.json", None)):
    p = os.path.join(DATA, fichero)
    if not os.path.exists(p):
        continue
    for s in json.load(open(p, encoding="utf-8")):
        ruta = os.path.join(DOCS, base, s.strip("/")) if base else os.path.join(DOCS, s.strip("/"))
        if not os.path.exists(os.path.join(ruta, "index.html")):
            fallos[f"URL histórica sin página ni redirección ({fichero})"].append(s)

# ── Informe ──────────────────────────────────────────────────────────
print(f"Páginas de producto: {len(productos)}  {dict(collections.Counter(c for c, *_ in productos.values()))}")
if not fallos:
    print("✅ Todo OK")
    sys.exit(0)
total = 0
for k, v in sorted(fallos.items(), key=lambda kv: -len(kv[1])):
    total += len(v)
    print(f"\n❌ {k}: {len(v)}")
    for x in v[:5]:
        print("   ·", x)
    if len(v) > 5:
        print(f"   · … y {len(v) - 5} más")
print(f"\n{total} fallos en {len(fallos)} tipos")
sys.exit(1)
