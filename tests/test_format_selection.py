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
