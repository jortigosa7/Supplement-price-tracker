"""
tests/test_format_selection.py — Verifica que precio y peso salen siempre del mismo formato
y que se elige el formato con mejor €/kg.

Ejecutar con: python -m pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scrapers.base import seleccionar_mejor_formato


class TestSeleccionarMejorFormato:

    def test_elige_mejor_euro_por_kg(self):
        """El formato más barato por kg debe ganar, aunque no sea el más barato en precio total."""
        formatos = [
            (0.030, 1.42),   # 30g muestra: 47.3 €/kg
            (0.500, 7.35),   # 500g: 14.7 €/kg
            (2.000, 21.03),  # 2kg: 10.5 €/kg  ← mejor
        ]
        best = seleccionar_mejor_formato(formatos)
        assert best is not None
        peso, precio = best
        assert peso == 2.000
        assert precio == 21.03

    def test_formato_unico(self):
        formatos = [(1.0, 15.0)]
        best = seleccionar_mejor_formato(formatos)
        assert best == (1.0, 15.0)

    def test_lista_vacia_devuelve_none(self):
        assert seleccionar_mejor_formato([]) is None

    def test_ignora_formatos_con_peso_cero(self):
        formatos = [(0.0, 5.0), (1.0, 10.0)]
        best = seleccionar_mejor_formato(formatos)
        assert best == (1.0, 10.0)

    def test_ignora_formatos_con_precio_cero(self):
        formatos = [(1.0, 0.0), (0.5, 8.0)]
        best = seleccionar_mejor_formato(formatos)
        assert best == (0.5, 8.0)

    def test_todos_invalidos_devuelve_none(self):
        formatos = [(0.0, 5.0), (1.0, 0.0)]
        assert seleccionar_mejor_formato(formatos) is None

    def test_desempate_por_euro_kg_exacto(self):
        """Dos formatos con mismo €/kg: devuelve cualquiera de los dos (no importa cuál)."""
        formatos = [(1.0, 10.0), (2.0, 20.0)]  # ambos a 10 €/kg
        best = seleccionar_mejor_formato(formatos)
        peso, precio = best
        assert abs(precio / peso - 10.0) < 0.01

    def test_caso_real_proteina_soja(self):
        """Caso real: Proteína de soja aislada HSN — 30g muestra vs 2kg."""
        formatos = [
            (0.030, 1.42),   # muestra: 47.3 €/kg
            (2.000, 21.03),  # 2kg: 10.5 €/kg ← mejor
        ]
        best = seleccionar_mejor_formato(formatos)
        assert best[0] == 2.0, "Debe elegir el formato 2kg, no la muestra de 30g"

    def test_precio_y_peso_misma_tupla(self):
        """Garantía de consistencia: el peso y el precio devueltos pertenecen al mismo formato."""
        formatos = [
            (0.5, 8.0),   # 16 €/kg
            (1.0, 12.0),  # 12 €/kg ← mejor
            (2.0, 30.0),  # 15 €/kg
        ]
        best = seleccionar_mejor_formato(formatos)
        # Verificar que el par (peso, precio) existe exactamente en la lista original
        assert best in formatos, "El par (peso, precio) debe pertenecer al listado original"
        assert best == (1.0, 12.0)


class TestNombreConFormatoMyProtein:
    """El nombre de MyProtein solo puede llevar el peso del formato elegido."""

    def _fn(self):
        from scrapers.myprotein import _nombre_con_formato
        return _nombre_con_formato

    def test_listado_sin_peso_añade_formato(self):
        assert self._fn()("Impact Whey Protein", 2.5) == "Impact Whey Protein 2.5kg"

    def test_catalogo_con_otro_peso_lo_sustituye(self):
        from limpieza import extraer_peso_kg
        nombre = self._fn()("Batidos Essential 2.5kg", 1.0)
        assert nombre == "Batidos Essential 1kg"
        assert extraer_peso_kg(nombre) == 1.0
        nombre = self._fn()("Mezcla de Rendimiento Todo-En-Uno 2.5kg", 5.0)
        assert extraer_peso_kg(nombre) == 5.0
        nombre = self._fn()("Creatina en polvo micronizada 500g", 0.25)
        assert nombre == "Creatina en polvo micronizada 250g"

    def test_catalogo_con_mismo_peso_no_cambia_id(self):
        assert self._fn()("Total Protein 5kg", 5.0) == "Total Protein 5kg 5kg"
        assert self._fn()("Origin Shred Pre-Workout 660g", 0.66) == "Origin Shred Pre-Workout 660g 660g"


def _html_batidos(variantes):
    """Página mínima de MyProtein con un ProductGroup (formato actual del JSON-LD)."""
    import json
    base = "https://www.myprotein.es/p/nutricion-deportiva/batidos-essential/16670299/"
    has_variant = [
        {
            "@type": "Product",
            "sku": sku,
            "name": f"Batidos Essential {nombre}",
            "offers": {
                "@type": "Offer",
                "price": precio,
                "url": f"{base}?variation={sku}",
                "availability": f"https://schema.org/{'InStock' if stock else 'OutOfStock'}",
            },
        }
        for sku, nombre, precio, stock in variantes
    ]
    schema = {"@context": "https://schema.org", "@type": "ProductGroup",
              "name": "Batidos Essential", "hasVariant": has_variant}
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'


# Datos reales de la ficha (13 nov 2026): el 1 kg a 15 € solo existe en tres sabores;
# la variante por defecto es el 2,5 kg de chocolate a 78,99 €.
_BATIDOS = [
    ("16747355", "2.5KG - 70raciones Chocolate y Caramelo (Fudge)", "78.99", True),
    ("16670305", "2.5KG - 70raciones Vanilla Honeycomb", "78.99", True),
    ("16914179", "1KG - 28raciones Banana Milkshake", "15", True),
    ("16914180", "1KG - 28raciones Strawberry Ice Cream", "15", True),
    ("17537772", "500G - 14raciones Chocolate y Caramelo (Fudge)", "19.99", True),
    ("17537773", "500G - 14raciones Strawberry Ice Cream", "10", True),
]


class TestVarianteMyProtein:
    """El enlace tiene que abrir la variante del precio que enseñamos."""

    def test_url_de_la_variante_elegida(self):
        from scrapers.myprotein import _extraer_variantes, _url_variante
        html = _html_batidos(_BATIDOS)
        variantes, _ = _extraer_variantes(html)
        peso, precio = seleccionar_mejor_formato(variantes)
        assert (peso, precio) == (1.0, 15.0)
        url = _url_variante(html, peso, precio)
        assert url.endswith("?variation=16914179")

    def test_ignora_sabores_agotados(self):
        """Si el formato barato está agotado en todos los sabores, no puede ser el precio."""
        from scrapers.myprotein import _extraer_variantes, _url_variante
        filas = [(s, n, p, not n.startswith("1KG")) for s, n, p, _ in _BATIDOS]
        html = _html_batidos(filas)
        variantes, _ = _extraer_variantes(html)
        assert 1.0 not in dict(variantes)
        peso, precio = seleccionar_mejor_formato(variantes)
        assert (peso, precio) == (0.5, 10.0)  # 500 g fresa, 20 €/kg
        assert _url_variante(html, peso, precio).endswith("?variation=17537773")

    def test_todo_agotado_mantiene_precio(self):
        from scrapers.myprotein import _extraer_variantes
        filas = [(s, n, p, False) for s, n, p, _ in _BATIDOS]
        variantes, _ = _extraer_variantes(_html_batidos(filas))
        assert seleccionar_mejor_formato(variantes) == (1.0, 15.0)

    def test_sin_variante_no_hay_url(self):
        from scrapers.myprotein import _url_variante
        assert _url_variante(_html_batidos(_BATIDOS), 1.0, 14.0) is None


class TestUrlCanonica:

    def test_awin_con_variante_igual_a_ficha(self):
        from scrapers.base import url_canonica
        ficha = "https://www.myprotein.es/p/nutricion-deportiva/batidos-essential/16670299/"
        awin = ("https://www.awin1.com/cread.php?awinmid=10603&awinaffid=2845182&ued="
                "https%3A%2F%2Fwww.myprotein.es%2Fp%2Fnutricion-deportiva%2Fbatidos-essential"
                "%2F16670299%2F%3Fvariation%3D16914179")
        assert url_canonica(awin) == ficha
        assert url_canonica(ficha + "?variation=16914179") == ficha
        assert url_canonica(ficha) == ficha

    def test_awin_convierte_a_la_variante(self):
        import build
        p = {"precios": [{
            "tienda": "MyProtein",
            "url_afiliado": "https://www.myprotein.es/p/x/batidos-essential/16670299/",
            "url_variante": "https://www.myprotein.es/p/x/batidos-essential/16670299/?variation=16914179",
        }, {
            "tienda": "MyProtein",
            "url_afiliado": "https://www.myprotein.es/p/x/otro/1/",
            "url_variante": float("nan"),  # columna vacía en datasets viejos
        }]}
        build.aplicar_afiliados_awin([p])
        a, b = p["precios"]
        assert "%3Fvariation%3D16914179" in a["url_afiliado"]
        assert b["url_afiliado"].endswith("ued=https%3A%2F%2Fwww.myprotein.es%2Fp%2Fx%2Fotro%2F1%2F")
        assert "url_variante" not in a and "url_variante" not in b
