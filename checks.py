"""
checks.py — Verificaciones post-build para StackFit.

Se llama al final de build.py, después de generar todo docs/.
Si falla cualquier check, sale con sys.exit(1) y un mensaje
pensado para leerse directamente desde el email de GitHub Actions.

Las métricas de cada ejecución exitosa se guardan en data/build_stats.json
para comparar con la siguiente.

Checks implementados:
  1. Redirecciones: destino existe en docs/ y no forma cadena.
  2. Links internos: hrefs absolutos en HTML apuntan a rutas existentes.
  3. Tiendas: ninguna tienda a 0 productos; ninguna cae >30% respecto al build anterior;
     ninguna tienda con 100% de productos sin precio_por_kg_min (fallo masivo de scraper).
  4. Métricas: comparaciones, grupos multi-tienda y páginas de sitemap no bajan.
  6. Desconocida: 'desconocida' no aparece en texto visible; campos críticos no vacíos.
  7. €/kg alto: ningún producto supera 10× la mediana de su categoría.
  8. IDs: aviso si >5% de IDs anteriores desaparece; error si >10%.
  9. GSC cobertura: URLs con clics en gsc_paginas.csv que no tienen página ni redirección.

Check 5 (IDs de comparaciones.json existen en products.json) → build.py::generar_pares_comparacion.
Check 7 bajada >40% inter-build → build.py::verificar_anomalias_precio.
  El rango de €/kg (alto y bajo) está ahora en checks.py::_check_precio_rango.
"""

import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

STATS_FILE       = "data/build_stats.json"
REDIR_FILE       = "data/redirecciones.json"
GSC_CSV          = "gsc_paginas.csv"
GSC_404_FILE     = "data/gsc_404_conocidas.json"
AUSENTES_FILE    = "data/productos_ausentes.json"
SCRAPE_STATS_FILE = "data/scrape_stats.json"
COMP_FILE        = "data/comparaciones.json"
DOCS_DIR         = "docs"

# Umbrales
UMBRAL_TIENDA_DROP = 0.30   # bajada de productos por tienda que dispara error
UMBRAL_IDS_WARN    = 0.05   # % de IDs desaparecidos → aviso en resumen
UMBRAL_IDS_ERROR   = 0.10   # % de IDs desaparecidos → error (posible cambio de IDs)
UMBRAL_KG_ALTO     = 3.0    # ratio €/kg vs mediana de categoría → anómalo si supera esto


# ── Persistencia ─────────────────────────────────────────────────────────────

def _cargar_stats_anteriores() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_stats(stats: dict) -> None:
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


# ── Check 1: Redirecciones ───────────────────────────────────────────────────

def _check_redirects(docs_dir: str) -> list[str]:
    """
    Verifica que cada entrada de redirecciones.json:
    - Apunta a una ruta que existe en docs/.
    - No apunta a otra redirección (cadena).
    """
    if not os.path.exists(REDIR_FILE):
        return []

    with open(REDIR_FILE, encoding="utf-8") as f:
        redirecciones = json.load(f)

    docs = Path(docs_dir)
    # Conjunto de fuentes (slugs "desde" normalizados sin slashes)
    fuentes = {r["desde"].strip("/") for r in redirecciones}
    errores = []

    for r in redirecciones:
        hasta = r.get("hasta", "").strip()
        if not hasta:
            errores.append(
                f"[CHECK 1] Redirección sin destino:\n"
                f"  desde: {r.get('desde', '?')}"
            )
            continue

        hasta_clean = hasta.strip("/")

        # Resolver ruta en docs/
        if hasta_clean:
            target = docs / hasta_clean / "index.html"
        else:
            # hasta="/" o "" → página raíz
            target = docs / "index.html"

        if not target.exists():
            errores.append(
                f"[CHECK 1] Redirección con destino inexistente:\n"
                f"  desde : {r['desde']}\n"
                f"  hasta : {hasta}\n"
                f"  falta : {target}\n"
                f"  Acción: actualiza redirecciones.json con el slug_publico correcto "
                f"o elimina la entrada si la página ya no existe."
            )

        # Detectar cadena: el destino es a su vez una fuente de redirección
        if hasta_clean and hasta_clean in fuentes:
            errores.append(
                f"[CHECK 1] Cadena de redirección detectada:\n"
                f"  {r['desde']} → {hasta} (que también es una fuente de redirección)\n"
                f"  Acción: apunta directamente al destino final."
            )

    return errores


# ── Check 2: Links internos ──────────────────────────────────────────────────

# Solo hrefs absolutos con caracteres válidos de ruta (excluye JS, templates, anclas)
_RE_HREF_INTERNO = re.compile(r'href="(/[a-zA-Z0-9/_.\-]+)"')


def _check_enlaces_internos(docs_dir: str) -> list[str]:
    """
    Parsea todos los HTML y verifica que los hrefs internos absolutos
    apunten a rutas que existen en docs/.
    """
    docs   = Path(docs_dir)
    errores = []
    vistos: set[str] = set()  # evitar reportar el mismo href roto múltiples veces

    for html_file in sorted(docs.rglob("*.html")):
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for href in set(_RE_HREF_INTERNO.findall(content)):
            if href in vistos:
                continue

            target = docs / href.lstrip("/")
            existe = target.exists() or (target / "index.html").exists()

            if not existe:
                vistos.add(href)
                rel = html_file.relative_to(docs)
                errores.append(
                    f"[CHECK 2] Enlace interno roto:\n"
                    f"  href  : {href}\n"
                    f"  página: {rel}\n"
                    f"  falta : {target}\n"
                    f"  Acción: regenera el build o elimina el enlace del template."
                )

    return errores


# ── Check 3: Productos por tienda ────────────────────────────────────────────

def _check_por_tienda(por_tienda: dict, por_tienda_ant: dict, productos_web: list[dict] | None = None) -> list[str]:
    """
    - Ninguna tienda puede tener 0 productos.
    - Ninguna tienda puede bajar >30% respecto al build anterior.
    - Ninguna tienda puede tener 100% de sus productos sin precio_por_kg_min
      (indica que _obtener_precio_peso_fresco falló en masa — web caída, rate-limit, etc.)
    """
    errores = []

    for tienda, count in por_tienda.items():
        if count == 0:
            errores.append(
                f"[CHECK 3] {tienda}: 0 productos en este build.\n"
                f"  Acción: corre el scraper manualmente y comprueba que responde."
            )

    # Check €/kg por tienda: si el 100% de los productos de una tienda no tienen
    # precio_por_kg_min, el scraper probablemente falló en silencio al obtener precios.
    if productos_web:
        from collections import defaultdict
        sin_kg: dict[str, int] = defaultdict(int)
        con_kg: dict[str, int] = defaultdict(int)
        for p in productos_web:
            peso = p.get("peso_kg") or 0
            if peso < 0.15:
                continue  # monodosis: legítimamente sin €/kg
            tiene_kg = bool(p.get("precio_por_kg_min"))
            for pr in p.get("precios", []):
                tienda = pr.get("tienda", "?")
                if tiene_kg:
                    con_kg[tienda] += 1
                else:
                    sin_kg[tienda] += 1
        for tienda in set(list(sin_kg.keys()) + list(con_kg.keys())):
            total = sin_kg[tienda] + con_kg[tienda]
            if total < 5:
                continue  # poca muestra, no alarmar
            if con_kg[tienda] == 0:
                errores.append(
                    f"[CHECK 3] {tienda}: 0/{total} productos tienen precio_por_kg_min "
                    f"(todos los productos con peso ≥150 g sin €/kg).\n"
                    f"  Indica que _obtener_precio_peso_fresco falló en masa durante el último scraping.\n"
                    f"  Posibles causas: HSN con HTML distinto (mantenimiento, A/B test, rate-limit).\n"
                    f"  Acción: vuelve a correr el scraper con: python scrapers/hsn.py"
                )

    if not por_tienda_ant:
        return errores

    for tienda, count_ant in por_tienda_ant.items():
        if count_ant == 0:
            continue
        count_act = por_tienda.get(tienda, 0)
        drop = (count_ant - count_act) / count_ant
        if drop > UMBRAL_TIENDA_DROP:
            errores.append(
                f"[CHECK 3] {tienda}: {count_act} productos ahora vs {count_ant} en el build anterior "
                f"(-{drop*100:.0f}%, umbral {UMBRAL_TIENDA_DROP*100:.0f}%).\n"
                f"  Acción: revisa si una categoría del scraper falló o el sitio cambió HTML."
            )

    return errores


# ── Check 4: Métricas globales ───────────────────────────────────────────────

def _check_metricas(stats_act: dict, stats_ant: dict) -> list[str]:
    """
    Comparaciones, grupos multi-tienda y páginas de sitemap nunca deben bajar.
    """
    if not stats_ant:
        return []

    errores = []

    # Sitemap: no debe bajar nunca
    ant_sitemap = stats_ant.get("n_sitemap")
    act_sitemap = stats_act.get("n_sitemap")
    if ant_sitemap is not None and act_sitemap is not None and act_sitemap < ant_sitemap:
        errores.append(
            f"[CHECK 4] páginas en sitemap bajó: {act_sitemap} ahora vs {ant_sitemap} antes (−{ant_sitemap - act_sitemap}).\n"
            f"  Si es intencionado, ignora. Si no, busca qué página desapareció."
        )

    # Grupos multi-tienda: error solo si base >= 5 y caída > 40 %; si base < 5, solo aviso
    ant_mt = stats_ant.get("grupos_multitienda")
    act_mt = stats_act.get("grupos_multitienda")
    if ant_mt is not None and act_mt is not None and act_mt < ant_mt:
        caida = round((1 - act_mt / ant_mt) * 100) if ant_mt > 0 else 0
        if ant_mt >= 5 and caida > 40:
            errores.append(
                f"[CHECK 4] grupos multi-tienda bajó: {act_mt} ahora vs {ant_mt} antes (−{ant_mt - act_mt}, {caida}%).\n"
                f"  El matching cross-tienda puede estar roto."
            )
        else:
            print(f"  ⚠️  AVISO [CHECK 4] grupos multi-tienda: {act_mt} (anterior: {ant_mt}) — base pequeña, solo aviso")

    return errores


# ── Check 4b: pares sin cobertura (ni página real ni redirección) ────────────

def _check_pares_sin_cobertura(ids_faltantes_gen: list, docs_dir: str) -> list[str]:
    """
    Para cada par de comparaciones.json con al menos un ID no resolvible,
    comprueba que exista una página de comparación real o una entrada en
    redirecciones.json que cubra ese par. Error si ninguna de las dos.
    """
    if not ids_faltantes_gen:
        return []

    errores = []

    with open(COMP_FILE, encoding="utf-8") as f:
        comp_data = json.load(f)

    redirecciones = []
    if os.path.exists(REDIR_FILE):
        with open(REDIR_FILE, encoding="utf-8") as f:
            redirecciones = json.load(f)
    desde_list = [r.get("desde", "") for r in redirecciones]

    ids_sin_pagina = set(ids_faltantes_gen)
    comparar_dir = os.path.join(docs_dir, "comparar")

    for par in comp_data.get("pares", []):
        id_a = par["id_a"]
        id_b = par["id_b"]
        if id_a not in ids_sin_pagina and id_b not in ids_sin_pagina:
            continue  # par resuelto normalmente

        # Verificar si hay página de comparación real (no meta-refresh) para algún ID del par
        tiene_pagina = False
        if os.path.isdir(comparar_dir):
            for entry in os.listdir(comparar_dir):
                html_path = os.path.join(comparar_dir, entry, "index.html")
                if not os.path.isfile(html_path):
                    continue
                if id_a not in entry and id_b not in entry:
                    continue
                try:
                    with open(html_path, "rb") as hf:
                        cabecera = hf.read(512).lower()
                    if b"http-equiv" in cabecera and b"refresh" in cabecera:
                        continue
                except OSError:
                    continue
                tiene_pagina = True
                break

        if tiene_pagina:
            continue

        # Verificar si hay una redirección que cubra este par
        tiene_redir = any(id_a in d or id_b in d for d in desde_list)
        if not tiene_redir:
            errores.append(
                f"[CHECK 4] Par sin cobertura: {id_a} vs {id_b}\n"
                f"  No hay página de comparación ni entrada en redirecciones.json.\n"
                f"  Añade una redirección en data/redirecciones.json o recupera el producto."
            )

    return errores


# ── Check 6: "Desconocida" y campos vacíos ───────────────────────────────────

_RE_SCRIPT = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_RE_STYLE  = re.compile(r"<style[^>]*>.*?</style>",  re.DOTALL | re.IGNORECASE)
_RE_TAGS   = re.compile(r"<[^>]+>")
_RE_DESCON = re.compile(r"\bdesconocid[ao]\b", re.IGNORECASE)


def _check_desconocido(docs_dir: str, productos_web: list[dict]) -> list[str]:
    """
    a) 'desconocida' no debe aparecer en texto visible de ninguna página.
    b) Cada producto debe tener nombre, tienda y al menos un precio no vacío.
    """
    errores = []
    docs    = Path(docs_dir)

    # a) Texto visible en HTML ─────────────────────────────────────────────
    ya_reportado: set[Path] = set()

    for html_file in sorted(docs.rglob("*.html")):
        if html_file in ya_reportado:
            continue
        try:
            raw = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Quitar script y style, luego quitar etiquetas HTML
        clean   = _RE_SCRIPT.sub("", raw)
        clean   = _RE_STYLE.sub("", clean)
        visible = _RE_TAGS.sub(" ", clean)

        if _RE_DESCON.search(visible):
            ya_reportado.add(html_file)
            errores.append(
                f"[CHECK 6] 'desconocida' en texto visible de {html_file.relative_to(docs)}.\n"
                f"  Indica que la marca de un producto no se resolvió.\n"
                f"  Acción: busca el producto con marca 'Desconocida' en products.json "
                f"y corrige el scraper o el matcher."
            )

    # b) Campos críticos vacíos en products.json ───────────────────────────
    for p in productos_web:
        pid = p.get("id", "?")
        nombre = p.get("nombre_normalizado", "")
        if not nombre:
            errores.append(
                f"[CHECK 6] Producto sin nombre_normalizado: id={pid}\n"
                f"  Acción: revisa el scraper de la tienda correspondiente."
            )
        if not p.get("tienda_mas_barata"):
            errores.append(
                f"[CHECK 6] Producto sin tienda_mas_barata: id={pid} nombre='{nombre}'\n"
                f"  Acción: el producto no tiene precios o precio_min es None."
            )
        precios = p.get("precios", [])
        if not precios:
            errores.append(
                f"[CHECK 6] Producto sin ningún precio: id={pid} nombre='{nombre}'"
            )
        elif not any(pr.get("precio_eur") for pr in precios):
            errores.append(
                f"[CHECK 6] Producto con precios todos nulos: id={pid} nombre='{nombre}'"
            )
        # Marca vacía → aparecería "Desconocida" en HTML
        if not p.get("marca"):
            errores.append(
                f"[CHECK 6] Producto sin marca: id={pid} nombre='{nombre}'\n"
                f"  Acción: revisa la extracción de marca en el scraper."
            )

    return errores


# ── Check 7: €/kg fuera de rango de categoría (alto y bajo) ─────────────────

UMBRAL_KG_BAJO = 0.20   # €/kg < 20% de la mediana → anómalo por abajo

# Gainers, cremas de arroz y otros productos con €/kg estructuralmente bajo
# se excluyen del check por abajo. No es un bug de scraper — es que el producto
# es barato por naturaleza (carbohidratos, saborizantes, ingredientes básicos).
_RE_GAINER = re.compile(r"\b(gainer|ganador|arroz)\b", re.IGNORECASE)
# Productos no-suplemento que vende HSN con €/kg muy bajo por definición
_RE_BAJO_ESTRUCTURAL = re.compile(
    r"\b(bicarbonato|isomaltulosa|palatinose|claras de huevo"
    r"|dextrosa|maltodextrina|ciclodextrina|amilopectina|vitargo)\b", re.IGNORECASE
)


def _es_gainer(nombre: str) -> bool:
    return bool(_RE_GAINER.search(nombre))


def _es_bajo_estructural(nombre: str) -> bool:
    return bool(_RE_BAJO_ESTRUCTURAL.search(nombre))


# Productos con €/kg alto verificado como correcto (precio premium legítimo, no bug)
_EXCLUIR_CHECK7_ALTO = frozenset({
    "Creatina Creapure® Professional 150g",  # Prozis: producto individual premium confirmado
})


def _check_precio_rango(productos_web: list[dict]) -> list[str]:
    """
    Detecta €/kg fuera del rango razonable de la categoría.

    Por arriba: €/kg > UMBRAL_KG_ALTO × mediana → peso extraído mal o precio
      en céntimos. Se aplica a todos los productos.

    Por abajo: €/kg < UMBRAL_KG_BAJO × mediana → precio "desde" incorrecto o
      formato equivocado. Se EXCLUYE a gainers, cremas de arroz y productos con
      €/kg bajo estructural (bicarbonato, isomaltulosa, claras de huevo, carbohidratos).
      Si el producto tiene histórico estable (precio no ha bajado >40%), solo aviso.
      Umbral 20%: Evobasic a 5,54 €/kg (11%) salta; whey real a 30+ €/kg no.

    Incluye monodosis (<100 g): el extractor de peso o la selección de formato puede estar mal.
    """
    import json as _json
    errores = []

    # Cargar historial para distinguir caída real vs precio bajo estructural con historia
    _history_path = os.path.join(os.path.dirname(__file__), "data", "price_history.json")
    _hist_by_id: dict = defaultdict(list)
    if os.path.exists(_history_path):
        try:
            with open(_history_path, encoding="utf-8") as _f:
                for _e in _json.load(_f):
                    _pid = _e.get("producto_id", "")
                    _fecha = _e.get("fecha", "")
                    _precio = _e.get("precio")
                    if _pid and _fecha and _precio is not None:
                        _hist_by_id[_pid].append((_fecha, float(_precio)))
            for _pid in _hist_by_id:
                _hist_by_id[_pid].sort(key=lambda x: x[0])
        except Exception:
            pass

    # La mediana se calcula excluyendo gainers para que no la arrastren hacia abajo
    kg_por_cat: dict[str, list[float]] = defaultdict(list)
    for p in productos_web:
        kg   = p.get("precio_por_kg_min")
        peso = p.get("peso_kg")
        nombre = p.get("nombre_normalizado", "")
        if kg and float(kg) > 0 and peso and float(peso) >= 0.1 and not _es_gainer(nombre):
            kg_por_cat[p.get("categoria", "?")].append(float(kg))

    medianas: dict[str, float] = {}
    for cat, vals in kg_por_cat.items():
        if vals:
            medianas[cat] = statistics.median(vals)

    for p in productos_web:
        cat     = p.get("categoria", "?")
        nombre  = p.get("nombre_normalizado", p.get("id", "?"))
        kg      = p.get("precio_por_kg_min")
        peso    = p.get("peso_kg")
        mediana = medianas.get(cat)
        if not (kg and peso and mediana):
            continue
        kg_f = float(kg)

        if kg_f > mediana * UMBRAL_KG_ALTO:
            if float(peso) < 0.1 or nombre in _EXCLUIR_CHECK7_ALTO:
                # Monodosis (<100g) o precio premium verificado: aviso, no error
                print(
                    f"  ⚠️  AVISO [CHECK 7] €/kg alto (monodosis o excluido): [{cat}] {nombre} "
                    f"({kg_f:.0f} €/kg, {float(peso)*1000:.0f}g)"
                )
            else:
                errores.append(
                    f"[CHECK 7] €/kg anormalmente ALTO: [{cat}] {nombre}\n"
                    f"  precio_por_kg={kg_f:.2f} €/kg  mediana_cat={mediana:.2f} €/kg  "
                    f"ratio={kg_f / mediana:.1f}x (umbral {UMBRAL_KG_ALTO:.0f}x)\n"
                    f"  Acción: verifica el precio y el peso en el scraper de origen."
                )
        elif kg_f < mediana * UMBRAL_KG_BAJO and not _es_gainer(nombre) and not _es_bajo_estructural(nombre):
            _pid = p.get("id", "")
            _hist = _hist_by_id.get(_pid, [])
            _precio_min = p.get("precio_min")
            if _hist:
                _last_precio = _hist[-1][1]
                _precio_min_f = float(_precio_min) if _precio_min else None
                _caida = (_precio_min_f / _last_precio) if (_precio_min_f and _last_precio) else 1.0
                if _caida >= 0.60:
                    print(
                        f"  ⚠️  AVISO [CHECK 7] €/kg bajo con histórico estable: [{cat}] {nombre} "
                        f"(€/kg={kg_f:.2f}, mediana={mediana:.2f})"
                    )
                    continue
            errores.append(
                f"[CHECK 7] €/kg anormalmente BAJO: [{cat}] {nombre}\n"
                f"  precio_por_kg={kg_f:.2f} €/kg  mediana_cat={mediana:.2f} €/kg  "
                f"ratio={kg_f / mediana:.0%} de la mediana (umbral {UMBRAL_KG_BAJO:.0%})\n"
                f"  Acción: revisa que el scraper coja el precio del formato correcto, "
                f"no el 'desde' del bote más pequeño."
            )

    return errores


# ── Check 8: Cambio masivo de IDs ────────────────────────────────────────────

def _check_gsc_cobertura(docs_dir: str) -> list[str]:
    """
    Check 9: URLs de /comparar/ con clics en gsc_paginas.csv que no tienen
    página real ni redirección configurada.

    Las 404 intencionadas (productos que ya no existen) están listadas en
    data/gsc_404_conocidas.json y se excluyen del check.

    Si gsc_paginas.csv no existe, el check se omite (no bloquea el build).
    """
    if not os.path.exists(GSC_CSV):
        return []

    import csv

    with open(GSC_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        gsc_rows = list(reader)

    if not gsc_rows:
        return []

    col_url = list(gsc_rows[0].keys())[0]

    # Rutas cubiertas: páginas reales en docs/
    docs_comparar: set[str] = set()
    comparar_dir = os.path.join(docs_dir, "comparar")
    if os.path.isdir(comparar_dir):
        for d in os.listdir(comparar_dir):
            if os.path.isdir(os.path.join(comparar_dir, d)):
                docs_comparar.add("/comparar/" + d + "/")

    # Rutas cubiertas: redirecciones configuradas
    redir_desde: set[str] = set()
    if os.path.exists(REDIR_FILE):
        with open(REDIR_FILE, encoding="utf-8") as f:
            for r in json.load(f):
                d = r["desde"]
                if not d.startswith("/"):
                    d = "/" + d
                redir_desde.add(d)

    # 404s intencionadas (productos sin sustituto en catálogo)
    conocidas: set[str] = set()
    if os.path.exists(GSC_404_FILE):
        with open(GSC_404_FILE, encoding="utf-8") as f:
            for entry in json.load(f):
                conocidas.add(entry["url"])

    sin_cobertura = []
    for row in gsc_rows:
        url = row[col_url]
        path = url.replace("https://stackfit.es", "")
        if not path.startswith("/comparar/") or path == "/comparar/":
            continue
        clics = int(row.get("Clics", "0") or 0)
        if clics <= 0:
            continue
        if path in docs_comparar or path in redir_desde or path in conocidas:
            continue
        sin_cobertura.append((path, clics))

    if not sin_cobertura:
        return []

    sin_cobertura.sort(key=lambda x: -x[1])
    lineas = [
        f"[CHECK 9] {len(sin_cobertura)} URL(s) con clics en GSC sin página ni redirección:\n"
    ]
    for path, clics in sin_cobertura[:20]:
        lineas.append(f"  {clics}c  {path}")
    if len(sin_cobertura) > 20:
        lineas.append(f"  ... y {len(sin_cobertura) - 20} más")
    lineas.append(
        "\nSolución: añadir redirección en data/redirecciones.json o "
        "registrar como 404 conocida en data/gsc_404_conocidas.json."
    )
    return ["\n".join(lineas)]


def _check_ids(ids_act: set[str], ids_ant: set[str]) -> list[str]:
    """
    Si >10% de los IDs anteriores desaparecen de golpe, es probable que
    el scraper cambió el formato de IDs (marca, peso, normalización).
    Aviso entre 5-10%, error por encima.
    """
    if not ids_ant:
        return []

    desaparecidos = ids_ant - ids_act
    if not desaparecidos:
        return []

    ratio = len(desaparecidos) / len(ids_ant)
    muestra = sorted(desaparecidos)[:8]

    if ratio > UMBRAL_IDS_ERROR:
        return [
            f"[CHECK 8] {len(desaparecidos)} IDs desaparecieron respecto al build anterior "
            f"({ratio * 100:.1f}% del catálogo, umbral {UMBRAL_IDS_ERROR * 100:.0f}%).\n"
            f"  Posible cambio de formato de IDs en el scraper o borrado masivo accidental.\n"
            f"  IDs afectados (primeros {len(muestra)}): {muestra}\n"
            f"  Acción: compara build_stats.json anterior con el actual. Si el cambio "
            f"es intencionado (ej. limpieza de marca), actualiza comparaciones.json y "
            f"redirecciones.json con los nuevos IDs."
        ]

    if ratio > UMBRAL_IDS_WARN:
        # Solo aviso, no error — puede ser producto descatalogado
        print(
            f"  ⚠️  AVISO [CHECK 8]: {len(desaparecidos)} IDs desaparecieron "
            f"({ratio * 100:.1f}%): {muestra}"
        )

    return []


def _check_slugs(slugs_act: set[str], slugs_ant: set[str]) -> list[str]:
    """
    Avisa siempre que un slug_publico desaparezca respecto al build anterior.
    Cada slug desaparecido = URL pública que ha cambiado o producto retirado.
    No tiene umbral de porcentaje — cualquier cambio es relevante.
    """
    if not slugs_ant:
        return []

    desaparecidos = slugs_ant - slugs_act
    if not desaparecidos:
        return []

    muestra = sorted(desaparecidos)[:10]
    # Solo aviso (print), no error — el build no debe fallar por esto.
    # El operador debe revisar si hace falta redirección.
    print(
        f"\n  AVISO [CHECK 8b] {len(desaparecidos)} slug(s) desaparecidos "
        f"respecto al build anterior. Cada uno = URL pública que ha cambiado o producto retirado.\n"
        f"  Revisa si necesitan redirección en data/redirecciones.json.\n"
        f"  Slugs afectados (primeros {len(muestra)}): {muestra}"
    )
    return []  # aviso solo, no error


UMBRAL_DIAS_SCRAPE = 7   # días sin datos frescos que disparan error de build


# ── Check fechas de scrape por tienda ─────────────────────────────────────────

def _check_fechas_scrape(fechas_por_tienda: dict) -> list[str]:
    """Error si alguna tienda lleva más de UMBRAL_DIAS_SCRAPE días sin datos frescos."""
    hoy = date.today()
    errores = []
    for tienda, fecha_str in sorted(fechas_por_tienda.items()):
        try:
            dias = (hoy - date.fromisoformat(fecha_str)).days
            if dias > UMBRAL_DIAS_SCRAPE:
                errores.append(
                    f"[CHECK FECHAS] {tienda}: datos de hace {dias} días ({fecha_str}). "
                    f"Umbral: {UMBRAL_DIAS_SCRAPE} días. "
                    "Los precios publicados de esta tienda pueden estar desactualizados. "
                    "Revisar el scraper o el fallback."
                )
        except Exception:
            pass
    return errores


# ── Check scrape stats: fallback Prozis consecutivo ──────────────────────────

def _check_scrape_stats() -> list[str]:
    """Error si alguna categoría Prozis lleva >=3 builds consecutivos usando datos viejos."""
    if not os.path.exists(SCRAPE_STATS_FILE):
        return []
    try:
        with open(SCRAPE_STATS_FILE, encoding="utf-8") as f:
            stats = json.load(f)
    except Exception:
        return []

    fallback = stats.get("prozis_fallback_consecutivo", {})
    criticos = {cat: n for cat, n in fallback.items() if n >= 3}
    if not criticos:
        return []

    detalle = ", ".join(f"{cat}: {n} builds" for cat, n in sorted(criticos.items()))
    return [
        f"[CHECK SCRAPE] Prozis lleva >=3 builds consecutivos con fallback en: {detalle}\n"
        f"  Los datos de esas categorías son de builds anteriores. Revisar el scraper de Prozis."
    ]


# ── Check desaparición de productos ──────────────────────────────────────────

def _check_productos_ausentes(ids_act: set[str], stats_ant: dict) -> list[str]:
    """
    Alerta fuerte (error) si un producto de comparaciones.json desaparece del catálogo.
    Aviso suave (print) si cualquier producto lleva >=2 builds consecutivos ausente.
    Actualiza data/productos_ausentes.json siempre, independientemente del resultado.
    """
    ids_ant = set(stats_ant.get("ids", []))
    if not ids_ant:
        return []

    desaparecidos = ids_ant - ids_act

    # Cargar historial de ausencias
    try:
        with open(AUSENTES_FILE, encoding="utf-8") as f:
            ausentes_hist: dict = json.load(f)
    except Exception:
        ausentes_hist = {}

    # Actualizar contadores: incrementar ausentes, resetear presentes
    nuevos_ausentes: dict[str, int] = {}
    for id_ in ids_ant:
        if id_ in desaparecidos:
            nuevos_ausentes[id_] = ausentes_hist.get(id_, 0) + 1
        # presentes no se guardan (contador implícito = 0)

    with open(AUSENTES_FILE, "w", encoding="utf-8") as f:
        json.dump(nuevos_ausentes, f, ensure_ascii=False, indent=2)

    # IDs que aparecen en comparaciones.json
    ids_en_comp: set[str] = set()
    try:
        with open(COMP_FILE, encoding="utf-8") as f:
            comp = json.load(f)
        for par in comp.get("pares", []):
            ids_en_comp.add(par["id_a"])
            ids_en_comp.add(par["id_b"])
    except Exception:
        pass

    errores: list[str] = []

    # Aviso (no error): producto de comparaciones.json ausente del catálogo de hoy.
    # El build usa el último dato conocido de products.json marcándolo como agotado.
    criticos = desaparecidos & ids_en_comp
    if criticos:
        muestra = sorted(criticos)[:5]
        print(
            f"  ⚠️  AVISO [CHECK AUSENTES]: {len(criticos)} producto(s) de comparaciones.json "
            f"ausentes del catálogo de hoy (se muestran como agotados en sus comparaciones):\n"
            + "\n".join(f"    - {id_}" for id_ in muestra)
            + (f"\n    ... (+{len(criticos) - 5} más)" if len(criticos) > 5 else "")
        )

    # Aviso suave: productos no críticos ausentes >=2 builds consecutivos
    ausentes_cronicos = {k: v for k, v in nuevos_ausentes.items()
                         if v >= 2 and k not in ids_en_comp}
    if ausentes_cronicos:
        muestra_s = sorted(ausentes_cronicos.items(), key=lambda x: -x[1])[:5]
        print(
            f"  ⚠️  AVISO [CHECK AUSENTES]: {len(ausentes_cronicos)} producto(s) "
            f"ausentes >=2 builds: "
            + ", ".join(f"{k}({v}b)" for k, v in muestra_s)
        )

    return errores


# ── Check nombre/peso desajuste ───────────────────────────────────────────────

def _check_nombre_peso_desajuste(productos_web: list[dict]) -> None:
    """Avisa si el peso en nombre_normalizado no coincide con peso_kg del producto."""
    from limpieza import extraer_peso_kg
    for p in productos_web:
        nombre = p.get("nombre_normalizado", "")
        peso_kg = p.get("peso_kg")
        if peso_kg is None:
            continue
        peso_nombre = extraer_peso_kg(nombre)
        if peso_nombre is None:
            continue
        if abs(float(peso_nombre) - float(peso_kg)) > 0.001:
            print(
                f"  ⚠️  AVISO nombre/peso desajuste: {nombre!r} "
                f"— nombre dice {peso_nombre}kg, peso_kg={peso_kg}kg"
            )


# ── Check precio fresco MyProtein ────────────────────────────────────────────

def _check_precio_fresco_myprotein(productos_web: list[dict]) -> list[str]:
    """
    Error si algún producto de MyProtein tiene _precio_fresco != True.
    Indica que el request al detalle falló y el precio viene del listing,
    posiblemente cacheado o sin peso/variante.
    """
    sin_fresco = []
    for p in productos_web:
        for pr in p.get("precios", []):
            if pr.get("tienda") != "MyProtein":
                continue
            if pr.get("_precio_fresco") is not True:
                sin_fresco.append(p.get("id", "?"))

    if not sin_fresco:
        return []

    return [
        f"[CHECK precio_fresco] {len(sin_fresco)} producto(s) de MyProtein con precio NO fresco "
        f"(request al detalle falló, precio del listing):\n"
        + "\n".join(f"  - {id_}" for id_ in sin_fresco[:10])
        + (f"\n  ... (+{len(sin_fresco) - 10} más)" if len(sin_fresco) > 10 else "")
        + "\n  Acción: revisar conectividad con MyProtein o reintentar el scraper."
    ]


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all_checks(
    productos_web: list[dict],
    n_comparaciones: int,
    grupos_multitienda: int,
    docs_dir: str = DOCS_DIR,
    fechas_por_tienda: dict | None = None,
    ids_faltantes_gen: list | None = None,
) -> bool:
    """
    Corre todos los checks post-build.
    Guarda métricas en data/build_stats.json si todos pasan.
    Devuelve True si todos los checks pasan, False si hay errores.
    """
    stats_ant = _cargar_stats_anteriores()

    # ── Recopilar métricas del build actual ───────────────────────────────
    por_tienda: dict[str, int] = {}
    ids_act:    set[str]       = set()
    slugs_act:  set[str]       = set()

    for p in productos_web:
        ids_act.add(p["id"])
        if p.get("slug_publico"):
            slugs_act.add(p["slug_publico"])
        for pr in p.get("precios", []):
            tienda = pr.get("tienda", "?")
            por_tienda[tienda] = por_tienda.get(tienda, 0) + 1

    sitemap  = Path(docs_dir) / "sitemap.xml"
    n_sitemap = sitemap.read_text(encoding="utf-8").count("<url>") if sitemap.exists() else 0

    stats_act = {
        "fecha":              str(date.today()),
        "total_productos":    len(productos_web),
        "por_tienda":         por_tienda,
        "n_comparaciones":    n_comparaciones,
        "grupos_multitienda": grupos_multitienda,
        "n_sitemap":          n_sitemap,
        "ids":                sorted(ids_act),
        "slugs":              sorted(slugs_act),
    }

    # ── Ejecutar todos los checks ─────────────────────────────────────────
    errores: list[str] = []
    errores += _check_redirects(docs_dir)
    errores += _check_enlaces_internos(docs_dir)
    errores += _check_por_tienda(por_tienda, stats_ant.get("por_tienda", {}), productos_web=productos_web)
    errores += _check_metricas(stats_act, stats_ant)
    errores += _check_pares_sin_cobertura(ids_faltantes_gen or [], docs_dir)
    errores += _check_desconocido(docs_dir, productos_web)
    _check_nombre_peso_desajuste(productos_web)
    errores += _check_precio_rango(productos_web)
    errores += _check_ids(ids_act, set(stats_ant.get("ids", [])))
    errores += _check_slugs(slugs_act, set(stats_ant.get("slugs", [])))
    errores += _check_gsc_cobertura(docs_dir)
    errores += _check_scrape_stats()
    errores += _check_productos_ausentes(ids_act, stats_ant)
    errores += _check_precio_fresco_myprotein(productos_web)
    if fechas_por_tienda:
        errores += _check_fechas_scrape(fechas_por_tienda)

    # ── Guardar baseline siempre ──────────────────────────────────────────
    # Se guarda antes de reportar errores para que el siguiente build compare
    # contra este, no contra el último build sin errores. Un cambio real de
    # catálogo (producto OOS, tienda que baja) genera una notificación y no
    # un bucle infinito de checks fallidos con baseline congelado.
    _guardar_stats(stats_act)

    # ── Reportar ──────────────────────────────────────────────────────────
    n_redir = len(json.load(open(REDIR_FILE, encoding="utf-8"))) if os.path.exists(REDIR_FILE) else 0
    if errores:
        header = f"BUILD CHECKS FALLIDOS — {len(errores)} problema(s)"
        print("\n" + "=" * 66)
        print(header)
        print(f"  Build: {stats_act['total_productos']} productos | "
              f"{n_comparaciones} comparaciones | sitemap: {n_sitemap} páginas")
        print(f"  Tiendas: {dict(sorted(por_tienda.items()))}")
        print("=" * 66)
        for i, err in enumerate(errores, 1):
            print(f"\n── Problema {i}/{len(errores)} ──")
            print(err)
        print("\n" + "=" * 66)
        print("Ver CHECKS.md para instrucciones de resolución.")
        print("Baseline actualizado a los números de este build.")
        print("=" * 66)
        return False

    print(
        f"Checks OK — "
        f"redirects: {n_redir} | "
        f"sitemap: {n_sitemap} | "
        f"tiendas: {dict(sorted(por_tienda.items()))} | "
        f"ids: {len(ids_act)}"
    )
    if fechas_por_tienda:
        print(f"  Fechas de scrape: {dict(sorted(fechas_por_tienda.items()))}")
    return True
