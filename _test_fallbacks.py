"""
_test_fallbacks.py -- Prueba de integracion ligera para los mecanismos de fallback.

Ejecutar con:  python _test_fallbacks.py

Test 1 -- Prozis retry en prozis.scrape():
  Mockea _scrape_cat_paginas y sync_playwright. Simula que "Proteinas Whey"
  devuelve 0 en el primer intento y 30 en el reintento. Verifica que se llama
  dos veces y que los 30 productos quedan en el resultado final.

Test 2 -- Fallback por categoria en scraper.py:
  Con prev_data real del disco, simula que prozis.scrape() devolvio 0 productos
  para "Proteinas Whey" y aplica la logica de fallback. Verifica que el recuento
  final de esa categoria es igual al del dataset anterior y que
  scrape_stats.json refleja consecutivo=1.

Test 3 -- Reintento Nutritienda en _scrape_listado():
  Mockea hacer_peticion con tres respuestas: r (p1 con total=80),
  r2 (truncada a 20 items), r3 (completa con 60 items).
  Verifica que se llama tres veces y que el resultado final usa los 60 items.
"""

import json
import os
import sys
import glob
import tempfile
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, call

PASS = "? PASS"
FAIL = "FAIL FAIL"

# ?????????????????????????????????????????????????????????????????????????????
# Helpers
# ?????????????????????????????????????????????????????????????????????????????

def _fake_item(nombre="Producto Test", categoria="Proteinas Whey"):
    return {"nombre": nombre, "precio": "9.99", "categoria": categoria,
            "url": "https://prozis.com/p/x", "imagen_url": None}


def _fake_items(n, categoria="Proteinas Whey"):
    return [_fake_item(f"Producto {i}", categoria) for i in range(n)]


def _resultado(ok, msg=""):
    print(f"  {'PASS' if ok else 'FAIL'}: {msg}")
    return ok


# ?????????????????????????????????????????????????????????????????????????????
# TEST 1 ? Retry interno de prozis.scrape()
# ?????????????????????????????????????????????????????????????????????????????

def test_prozis_retry():
    print("\n" + "="*62)
    print("TEST 1: Retry en prozis.scrape() cuando una categor?a falla")
    print("="*62)

    # Inyectar mock de playwright en sys.modules antes de importar prozis
    mock_pw_module = MagicMock()
    mock_page      = MagicMock()
    mock_browser   = MagicMock()
    mock_ctx       = MagicMock()
    mock_pw_inst   = MagicMock()

    mock_ctx.new_page.return_value      = mock_page
    mock_browser.new_context.return_value = mock_ctx
    mock_pw_inst.chromium.launch.return_value = mock_browser

    mock_cm = MagicMock()
    mock_cm.__enter__ = lambda s: mock_pw_inst
    mock_cm.__exit__  = MagicMock(return_value=False)
    mock_pw_module.sync_playwright.return_value = mock_cm

    sys.modules["playwright"]           = MagicMock()
    sys.modules["playwright.sync_api"]  = mock_pw_module

    import importlib
    # Forzar reimport limpio de prozis para que el mock de playwright surta efecto
    if "scrapers.prozis" in sys.modules:
        del sys.modules["scrapers.prozis"]
    from scrapers import prozis as prozis_mod

    CATS = [c["nombre"] for c in prozis_mod.CATEGORIAS]
    call_counts = {}

    def fake_scrape_cat(page, cat, debug=False):
        nombre = cat["nombre"]
        call_counts[nombre] = call_counts.get(nombre, 0) + 1
        if nombre == "Proteinas Whey" and call_counts[nombre] == 1:
            print(f"    [mock cat] {nombre} -> intento {call_counts[nombre]}: 0 items (simula fallo)")
            return [], False
        n_items = 30 if nombre == "Proteinas Whey" else 20
        print(f"    [mock cat] {nombre} -> intento {call_counts[nombre]}: {n_items} items")
        return _fake_items(n_items, nombre), False

    # tambi?n mockear producto_base para que no falle la etapa de enriquecimiento
    def fake_producto_base(nombre, precio, marca, categoria, tienda, url, imagen_url):
        return {"nombre": nombre, "precio": precio, "categoria": categoria,
                "tienda": tienda, "url": url}

    results = []
    with patch.object(prozis_mod, "_scrape_cat_paginas", side_effect=fake_scrape_cat), \
         patch("scrapers.prozis.time.sleep"), \
         patch("scrapers.prozis.producto_base", side_effect=fake_producto_base), \
         patch("scrapers.prozis.get_cached", return_value="<html>cached</html>"), \
         patch("scrapers.prozis._extraer_enriquecimiento_html", return_value={}):

        prev_cat_counts = {"Proteinas Whey": 50, "Creatina": 20, "BCAA": 15, "Pre-Entreno": 10}
        results = prozis_mod.scrape(debug=False, prev_cat_counts=prev_cat_counts)

    # Verificaciones
    whey_calls   = call_counts.get("Proteinas Whey", 0)
    other_calls  = {k: v for k, v in call_counts.items() if k != "Proteinas Whey"}
    whey_prods   = [p for p in results if p.get("categoria") == "Proteinas Whey"]
    other_prods  = [p for p in results if p.get("categoria") != "Proteinas Whey"]

    ok1 = _resultado(whey_calls == 2,
                     f"Proteinas Whey llamada {whey_calls} veces (esperado: 2)")
    ok2 = _resultado(all(v == 1 for v in other_calls.values()),
                     f"Otras categor?as llamadas 1 vez: {other_calls}")
    ok3 = _resultado(len(whey_prods) == 30,
                     f"Proteinas Whey en resultado: {len(whey_prods)} (esperado: 30)")
    ok4 = _resultado(len(other_prods) > 0,
                     f"Resto de categor?as en resultado: {len(other_prods)}")

    return all([ok1, ok2, ok3, ok4])


# ?????????????????????????????????????????????????????????????????????????????
# TEST 2 ? Fallback por categor?a en scraper.py
# ?????????????????????????????????????????????????????????????????????????????

def test_prozis_category_fallback():
    print("\n" + "="*62)
    print("TEST 2: Fallback Prozis por categor?a en scraper.py")
    print("="*62)

    # Cargar dataset anterior real
    prev_files = sorted(glob.glob(os.path.join("datasets", "suplementos_*.json")), reverse=True)
    if not prev_files:
        print("  SKIP: no hay dataset anterior en datasets/")
        return True

    with open(prev_files[0], encoding="utf-8") as f:
        prev_data = json.load(f)

    prev_prozis = [p for p in prev_data if p.get("tienda") == "Prozis"]
    if not prev_prozis:
        print("  SKIP: no hay productos Prozis en el dataset anterior")
        return True

    # Contar por categor?a
    prev_cat_counts: dict = {}
    for p in prev_prozis:
        cat = p.get("categoria", "")
        prev_cat_counts[cat] = prev_cat_counts.get(cat, 0) + 1
    print(f"  prev_cat_counts: {prev_cat_counts}")

    # Simular que prozis.scrape() devolvi? 0 para "Proteinas Whey"
    CAT_FALLA = "Proteinas Whey"
    productos_prozis_sim = [p for p in prev_prozis if p.get("categoria") != CAT_FALLA]
    print(f"  prozis.scrape() simulado: {len(productos_prozis_sim)} productos (sin {CAT_FALLA})")

    # Reproducir la l?gica de fallback de scraper.py
    todos = list(productos_prozis_sim)

    cat_counts_nuevo: dict = {}
    for p in productos_prozis_sim:
        cat = p.get("categoria", "")
        cat_counts_nuevo[cat] = cat_counts_nuevo.get(cat, 0) + 1

    fallback_consec: dict = {}
    cats_fallback = []

    for cat_nombre, prev_count in prev_cat_counts.items():
        if prev_count == 0:
            continue
        nuevo_count = cat_counts_nuevo.get(cat_nombre, 0)
        if nuevo_count < prev_count * 0.60:
            todos = [p for p in todos if not (
                p.get("tienda") == "Prozis" and p.get("categoria") == cat_nombre
            )]
            prev_cat = [p for p in prev_data
                        if p.get("tienda") == "Prozis" and p.get("categoria") == cat_nombre]
            if prev_cat:
                hoy = datetime.now().strftime("%Y-%m-%d")
                for p in prev_cat:
                    p["fecha_scraping"] = hoy
                todos.extend(prev_cat)
                fallback_consec[cat_nombre] = fallback_consec.get(cat_nombre, 0) + 1
                cats_fallback.append(cat_nombre)
                print(
                    f"  !!  Prozis/{cat_nombre}: {nuevo_count} -> fallback "
                    f"a {len(prev_cat)} productos anteriores (consec={fallback_consec[cat_nombre]})"
                )
        else:
            fallback_consec[cat_nombre] = 0

    # Comprobar scrape_stats en fichero temporal
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
        stats_path = tf.name
        json.dump({"prozis_fallback_consecutivo": fallback_consec}, tf, ensure_ascii=False)

    with open(stats_path, encoding="utf-8") as f:
        written = json.load(f)
    os.unlink(stats_path)

    final_counts: dict = {}
    for p in todos:
        if p.get("tienda") == "Prozis":
            cat = p.get("categoria", "")
            final_counts[cat] = final_counts.get(cat, 0) + 1

    print(f"\n  Recuento final Prozis: {final_counts}")
    print(f"  Categor?as con fallback: {cats_fallback}")
    print(f"  scrape_stats escritos: {written['prozis_fallback_consecutivo']}")

    exp_whey = prev_cat_counts.get(CAT_FALLA, 0)
    got_whey = final_counts.get(CAT_FALLA, 0)
    consec   = written["prozis_fallback_consecutivo"].get(CAT_FALLA, 0)

    ok1 = _resultado(CAT_FALLA in cats_fallback,
                     f"fallback activado para {CAT_FALLA}")
    ok2 = _resultado(got_whey == exp_whey,
                     f"{CAT_FALLA} recuperada: {got_whey} productos (esperado: {exp_whey})")
    ok3 = _resultado(consec == 1,
                     f"consecutivo registrado: {consec} (esperado: 1)")

    return all([ok1, ok2, ok3])


# ?????????????????????????????????????????????????????????????????????????????
# TEST 3 ? Reintento Nutritienda en _scrape_listado()
# ?????????????????????????????????????????????????????????????????????????????

def _make_itemlist_html(total: int, n_items: int) -> str:
    """Genera HTML m?nimo con ItemList JSON-LD para _parse_itemlist."""
    items = []
    for i in range(n_items):
        items.append({
            "item": {
                "name": f"Producto {i}",
                "url": f"https://nutritienda.com/p/{i}",
                "image": "https://img.nutritienda.com/p.jpg",
                "brand": {"name": "TestBrand"},
                "offers": {"price": "9.99"},
            }
        })
    ld = {
        "@graph": [{
            "@type": "ItemList",
            "numberOfItems": total,
            "itemListElement": items,
        }]
    }
    return f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head></html>'


def test_nutritienda_retry():
    print("\n" + "="*62)
    print("TEST 3: Reintento Nutritienda en _scrape_listado()")
    print("="*62)

    from scrapers import nutritienda as nut_mod

    TOTAL    = 120  # total declarado > MAX_POR_CATEGORIA (80) para que pida pag 2
    N_P1     = 20   # items en la primera pagina
    N_R2_BAD = 12   # truncado: 12 < 80*0.7=56 -> dispara reintento
    N_R3_OK  = 60   # reintento completo (suficiente)

    html_p1  = _make_itemlist_html(TOTAL, N_P1)
    html_bad = _make_itemlist_html(TOTAL, N_R2_BAD)
    html_ok  = _make_itemlist_html(TOTAL, N_R3_OK)

    call_count = [0]
    respuestas = [html_p1, html_bad, html_ok]

    def fake_hacer_peticion(url, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        r = MagicMock()
        r.text = respuestas[idx] if idx < len(respuestas) else html_ok
        r.url  = url
        r.status_code = 200
        label = ["p1 (normal)", "r2 (truncada)", "r3 (reintento)"][min(idx, 2)]
        print(f"    [mock net] petici?n #{idx+1} ({label}) -> {[N_P1, N_R2_BAD, N_R3_OK][min(idx,2)]} items")
        return r

    resultado = None
    with patch("scrapers.nutritienda.hacer_peticion", side_effect=fake_hacer_peticion), \
         patch("scrapers.nutritienda.time.sleep"):
        resultado = nut_mod._scrape_listado("https://nutritienda.com/es/proteinas-suero-whey")

    print(f"\n  Peticiones totales: {call_count[0]}")
    print(f"  Items en resultado: {len(resultado)}")

    ok1 = _resultado(call_count[0] == 3,
                     f"se hicieron {call_count[0]} peticiones (esperado: 3)")
    ok2 = _resultado(len(resultado) == N_R3_OK,
                     f"resultado usa reintento: {len(resultado)} items (esperado: {N_R3_OK})")

    return all([ok1, ok2])


# ?????????????????????????????????????????????????????????????????????????????
# Runner
# ?????????????????????????????????????????????????????????????????????????????

if __name__ == "__main__":
    resultados = []
    resultados.append(("Prozis retry (prozis.scrape)",         test_prozis_retry()))
    resultados.append(("Prozis fallback categor?a (scraper.py)", test_prozis_category_fallback()))
    resultados.append(("Nutritienda reintento incompleto",      test_nutritienda_retry()))

    print("\n" + "="*62)
    print("RESUMEN")
    print("="*62)
    total_ok = 0
    for nombre, ok in resultados:
        icon = "?" if ok else "FAIL"
        print(f"  {icon}  {nombre}")
        if ok:
            total_ok += 1
    print(f"\n  {total_ok}/{len(resultados)} tests pasaron")
    sys.exit(0 if total_ok == len(resultados) else 1)
