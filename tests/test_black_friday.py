"""
tests/test_black_friday.py — Qué rebajas de Black Friday cuentan como reales.

Lo importante que se comprueba: que la referencia es lo que costaba antes de noviembre
(una subida en noviembre seguida de una "rebaja" al precio de siempre no cuenta), que no
se mezclan tiendas y que los listados con enlace solo llevan tiendas afiliadas.

Ejecutar con: python -m pytest tests/ -v
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import black_friday as bf

REF = bf.REFERENCIA_FIN  # 2026-11-01


def _hist(precios: list[float], tienda: str = "HSN", hasta: str = REF, cada_dias: int = 3) -> list[dict]:
    """Historial que termina el día antes de 'hasta', una observación cada 'cada_dias'."""
    fin = date.fromisoformat(hasta)
    n = len(precios)
    return [{"fecha": (fin - timedelta(days=cada_dias * (n - i))).isoformat(), "precio": p, "tienda": tienda}
            for i, p in enumerate(precios)]


class TestReferencia:

    def test_historial_corto_no_da_referencia(self):
        assert bf.referencia(_hist([40.0] * 5), "HSN") is None

    def test_habitual_es_la_mediana_y_minimo_el_de_30_dias(self):
        # 30 observaciones cada 3 días: las 10 últimas caen en los 30 días previos
        precios = [50.0] * 20 + [45.0] * 10
        ref = bf.referencia(_hist(precios), "HSN")
        assert ref["habitual"] == 50.0
        assert ref["minimo_30"] == 45.0

    def test_no_mezcla_tiendas(self):
        hist = _hist([40.0] * 20, tienda="HSN") + _hist([10.0] * 20, tienda="MyProtein")
        assert bf.referencia(hist, "HSN")["habitual"] == 40.0

    def test_precios_de_noviembre_no_entran_en_la_referencia(self):
        hist = _hist([40.0] * 20) + [{"fecha": "2026-11-05", "precio": 60.0, "tienda": "HSN"}]
        assert bf.referencia(hist, "HSN")["habitual"] == 40.0


class TestClasificar:
    REF_PLANA = {"habitual": 40.0, "minimo_30": 40.0, "n_fechas": 20}

    def test_por_debajo_del_minimo_y_del_habitual_es_rebaja_real(self):
        r = bf.clasificar(34.0, self.REF_PLANA)
        assert r["estado"] == "rebaja_real"
        assert r["rebaja_pct"] == 15.0

    def test_igual_al_minimo_reciente_no_es_rebaja_real(self):
        # Ya costó 36 € en octubre: más barato que de costumbre, pero no es nuevo
        r = bf.clasificar(36.0, {"habitual": 40.0, "minimo_30": 36.0, "n_fechas": 20})
        assert r["estado"] == "rebajado"

    def test_subida_en_noviembre_y_vuelta_al_precio_de_siempre_no_es_rebaja(self):
        # La tienda lo puso a 48 € en noviembre y ahora "lo rebaja" a 40 €: es lo de siempre
        assert bf.clasificar(40.0, self.REF_PLANA)["estado"] == "precio_habitual"

    def test_mas_caro_que_de_costumbre(self):
        assert bf.clasificar(43.0, self.REF_PLANA)["estado"] == "mas_caro"

    def test_rebaja_pequena_no_cuenta(self):
        # 2,5 % por debajo: dentro del margen de "precio de siempre"
        assert bf.clasificar(39.0, self.REF_PLANA)["estado"] == "precio_habitual"

    def test_caida_imposible_se_descarta(self):
        assert bf.clasificar(15.0, self.REF_PLANA) is None


def _producto(pid, tienda, precio, peso=1.0, **extra):
    return {"id": pid, "nombre_display": pid, "categoria": "proteina-whey", "peso_kg": peso,
            "tienda_mas_barata": tienda,
            "precios": [{"tienda": tienda, "precio_eur": precio, "url_afiliado": f"https://x/{pid}"}],
            **extra}


class TestAnalizar:

    def test_agregados_con_todas_las_tiendas_y_listados_solo_afiliadas(self):
        productos = [
            _producto("a", "HSN", 34.0),
            _producto("b", "Nutritienda", 34.0),
            _producto("c", "HSN", 40.0),
        ]
        hist = {pid: _hist([40.0] * 20, tienda=t) for pid, t in (("a", "HSN"), ("b", "Nutritienda"), ("c", "HSN"))}
        r = bf.analizar(productos, hist, {"HSN"})
        assert r["total"] == 3
        assert r["por_estado"]["rebaja_real"] == 2
        assert r["por_estado"]["precio_habitual"] == 1
        assert [x["id"] for x in r["rebajas_reales"]] == ["a"]
        assert r["por_tienda"]["Nutritienda"]["rebaja_real"] == 1

    def test_excluye_agotados_muestras_y_sospechosos(self):
        productos = [
            _producto("agotado", "HSN", 30.0, agotado=True),
            _producto("muestra", "HSN", 30.0, peso=0.03),
            _producto("raro", "HSN", 30.0),
        ]
        hist = {p["id"]: _hist([40.0] * 20) for p in productos}
        r = bf.analizar(productos, hist, {"HSN"}, ids_excluidos={"raro"})
        assert r["total"] == 0

    def test_sin_historial_no_cuenta(self):
        r = bf.analizar([_producto("nuevo", "HSN", 30.0)], {}, {"HSN"})
        assert r["total"] == 0


def test_pagina_abierta_hasta_una_semana_despues():
    assert bf.pagina_abierta("2026-12-08") is True
    assert bf.pagina_abierta("2026-12-09") is False


class TestInforme:
    """informe_black_friday.analizar_producto: subida previa y rebaja sobre precio inflado."""

    def _con_noviembre(self, pre_nov: float, campana: float) -> list[dict]:
        hist = _hist([40.0] * 20)
        hist += [{"fecha": f, "precio": pre_nov, "tienda": "HSN"} for f in ("2026-11-03", "2026-11-06", "2026-11-10")]
        hist += [{"fecha": f, "precio": campana, "tienda": "HSN"} for f in ("2026-11-20", "2026-11-28")]
        return hist

    def test_subida_y_vuelta_al_precio_de_siempre_es_rebaja_sobre_inflado(self):
        import informe_black_friday as inf
        r = inf.analizar_producto(self._con_noviembre(48.0, 40.0), "HSN")
        assert r["subida_previa"] is True
        assert r["estado_campana"] == "precio_habitual"
        assert r["inflado"] is True

    def test_rebaja_real_en_campana_no_es_inflado(self):
        import informe_black_friday as inf
        r = inf.analizar_producto(self._con_noviembre(40.0, 33.0), "HSN")
        assert r["subida_previa"] is False
        assert r["estado_campana"] == "rebaja_real"
        assert r["inflado"] is False

    def test_el_ultimo_dia_de_campana_cuenta(self):
        import informe_black_friday as inf
        hist = _hist([40.0] * 20) + [{"fecha": bf.CAMPANA_FIN, "precio": 30.0, "tienda": "HSN"}]
        assert inf.analizar_producto(hist, "HSN")["min_campana"] == 30.0
