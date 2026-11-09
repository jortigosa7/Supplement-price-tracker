"""
tests/test_minimos.py — Detección de mínimos reales y avisos de Telegram.

Lo importante que se comprueba: que un descuento habitual NO cuenta como oferta,
que no se mezclan tiendas ni precios viejos, y que un aviso no se repite.

Ejecutar con: python -m pytest tests/ -v
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import avisos_telegram
import minimos

HOY = "2026-11-09"


def _serie(precios: list[float], hoy: str = HOY, cada_dias: int = 3) -> list[tuple[str, float]]:
    """Serie previa a 'hoy': el último precio de la lista es el de la observación anterior."""
    fin = date.fromisoformat(hoy)
    n = len(precios)
    return [((fin - timedelta(days=cada_dias * (n - i))).isoformat(), p) for i, p in enumerate(precios)]


class TestEvaluarPrecio:

    def test_bajada_real_es_minimo_y_record(self):
        c = minimos.evaluar_precio(39.90, _serie([47.9] * 14), HOY)
        assert c is not None
        assert c["es_record"] is True
        assert c["precio_habitual"] == 47.9
        assert c["rebaja_pct"] == 16.7
        assert c["dias_historial"] == 42
        assert c["desde"] == HOY

    def test_precio_plano_no_es_oferta(self):
        assert minimos.evaluar_precio(47.9, _serie([47.9] * 14), HOY) is None

    def test_descuento_que_se_repite_cada_semana_no_es_oferta(self):
        # Rebajado la mitad de los días: ese es su precio normal, no una oferta
        assert minimos.evaluar_precio(30.0, _serie([45.0, 30.0] * 8), HOY) is None

    def test_si_ya_estuvo_mas_barato_no_es_minimo(self):
        assert minimos.evaluar_precio(40.0, _serie([47.9] * 6 + [38.0] + [47.9] * 7), HOY) is None

    def test_rebaja_pequena_no_cuenta(self):
        assert minimos.evaluar_precio(46.0, _serie([47.9] * 14), HOY) is None

    def test_poco_historial_no_cuenta(self):
        assert minimos.evaluar_precio(39.9, _serie([47.9] * 5), HOY) is None             # pocas fechas
        assert minimos.evaluar_precio(39.9, _serie([47.9] * 14, cada_dias=1), HOY) is None  # pocos días

    def test_caida_imposible_se_descarta(self):
        # -60 %: casi seguro que el scraper ha cogido otra variante
        assert minimos.evaluar_precio(19.0, _serie([47.9] * 14), HOY) is None

    def test_iguala_un_minimo_anterior(self):
        c = minimos.evaluar_precio(40.0, _serie([47.9] * 3 + [40.0] + [47.9] * 10), HOY)
        assert c is not None
        assert c["es_record"] is False

    def test_racha_cuenta_desde_el_primer_dia_y_sigue_siendo_record(self):
        serie = _serie([47.9] * 12 + [39.9, 39.9])
        c = minimos.evaluar_precio(39.9, serie, HOY)
        assert c is not None
        assert c["desde"] == serie[-2][0]
        assert c["es_record"] is True


def _producto(pid="evowhey-2kg-hsn", tienda="HSN", precio=39.9, fecha=HOY, **extra) -> dict:
    return {
        "id": pid, "nombre_display": "Evowhey 2 kg", "categoria": "proteina-whey",
        "tienda_mas_barata": tienda, "peso_kg": 2.0, "precio_por_kg_min": precio / 2,
        "store_rating_count": 500, "pagina_url": "/proteina-whey/evowhey-hsn/",
        "precios": [{"tienda": tienda, "precio_eur": precio, "fecha": fecha,
                     "url_afiliado": "https://tienda.example/afiliado"}],
        **extra,
    }


def _historial(pid="evowhey-2kg-hsn", tienda="HSN", precios=None) -> dict:
    precios = precios or [47.9] * 14
    return {pid: [{"producto_id": pid, "tienda": tienda, "fecha": f, "precio": p} for f, p in _serie(precios)]}


class TestDetectarMinimos:

    def test_detecta_el_minimo_con_sus_datos(self):
        res = minimos.detectar_minimos([_producto()], _historial(), {"HSN"})
        assert len(res) == 1
        assert res[0]["precio"] == 39.9
        assert res[0]["url_afiliado"] == "https://tienda.example/afiliado"
        assert res[0]["pagina_url"] == "/proteina-whey/evowhey-hsn/"

    def test_tienda_sin_afiliacion_no_entra(self):
        p = _producto(tienda="Nutritienda")
        assert minimos.detectar_minimos([p], _historial(tienda="Nutritienda"), {"HSN"}) == []

    def test_agotado_o_excluido_no_entra(self):
        assert minimos.detectar_minimos([_producto(agotado=True)], _historial(), {"HSN"}) == []
        assert minimos.detectar_minimos([_producto()], _historial(), {"HSN"}, ids_excluidos={"evowhey-2kg-hsn"}) == []

    def test_precio_de_un_scrape_anterior_no_entra(self):
        # La tienda se scrapeó hoy (otro producto lo prueba), pero este precio es de hace 4 días
        viejo = _producto(fecha="2026-11-05")
        otro = _producto(pid="otro-1kg-hsn", precio=20.0)
        assert minimos.detectar_minimos([viejo, otro], _historial(), {"HSN"}) == []

    def test_no_mezcla_historial_de_otra_tienda(self):
        hist = _historial(tienda="MyProtein")  # el historial es de otra tienda: HSN no tiene datos
        assert minimos.detectar_minimos([_producto()], hist, {"HSN", "MyProtein"}) == []

    def test_ordena_por_interes_no_solo_por_rebaja(self):
        popular = _producto(pid="popular-2kg-hsn", precio=40.0, store_rating_count=5000)
        raro = _producto(pid="raro-2kg-hsn", precio=36.0, store_rating_count=3)
        hist = {**_historial("popular-2kg-hsn"), **_historial("raro-2kg-hsn")}
        res = minimos.detectar_minimos([raro, popular], hist, {"HSN"})
        assert [m["id"] for m in res] == ["popular-2kg-hsn", "raro-2kg-hsn"]


def _minimo(pid="evowhey-2kg-hsn", precio=39.9, **extra) -> dict:
    return {
        "id": pid, "nombre": "Evowhey 2 kg", "tienda": "HSN", "fecha": HOY, "precio": precio,
        "precio_habitual": 47.9, "rebaja_pct": 16.7, "es_record": True, "dias_historial": 42,
        "precio_por_kg": 19.95, "url_afiliado": "https://tienda.example/a?x=1&y=2",
        "pagina_url_abs": "https://stackfit.es/proteina-whey/evowhey-hsn/",
        **extra,
    }


class TestAvisos:

    def test_no_repite_un_aviso_reciente(self):
        hoy = date.fromisoformat(HOY)
        enviados = [{"id": "evowhey-2kg-hsn", "tienda": "HSN", "precio": 39.9, "fecha": "2026-11-04"}]
        assert avisos_telegram.seleccionar_nuevos([_minimo()], enviados, hoy) == []

    def test_repite_si_baja_mas_o_si_ha_pasado_tiempo(self):
        hoy = date.fromisoformat(HOY)
        reciente = [{"id": "evowhey-2kg-hsn", "tienda": "HSN", "precio": 39.9, "fecha": "2026-11-04"}]
        antiguo = [{"id": "evowhey-2kg-hsn", "tienda": "HSN", "precio": 39.9, "fecha": "2026-10-01"}]
        assert len(avisos_telegram.seleccionar_nuevos([_minimo(precio=37.9)], reciente, hoy)) == 1
        assert len(avisos_telegram.seleccionar_nuevos([_minimo()], antiguo, hoy)) == 1

    def test_formato_del_aviso(self):
        texto = avisos_telegram.formatear_aviso(_minimo(), pendientes=2, ofertas_url="https://stackfit.es/ofertas/")
        assert "<b>Evowhey 2 kg</b> · HSN" in texto
        assert "<b>39,90 €</b>" in texto and "suele costar 47,90 €" in texto and "−17 %" in texto
        assert "Precio más bajo en 42 días" in texto
        assert 'href="https://tienda.example/a?x=1&amp;y=2"' in texto   # & escapado para Telegram
        assert "Enlace de afiliado" in texto
        assert "otros 2 productos" in texto

    def test_aviso_que_iguala_no_dice_record(self):
        texto = avisos_telegram.formatear_aviso(_minimo(es_record=False))
        assert "Iguala su mínimo de 42 días" in texto
        assert "más bajo" not in texto

    def test_nombre_con_html_no_rompe_el_mensaje(self):
        texto = avisos_telegram.formatear_aviso(_minimo(nombre="BCAA's <2:1:1> & más"))
        assert "BCAA&#x27;s &lt;2:1:1&gt; &amp; más" in texto


class _Respuesta:
    def __init__(self, status, cuerpo):
        self.status_code = status
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


class TestEnviar:

    def test_envio_correcto(self, monkeypatch):
        llamadas = []

        def fake_post(url, json=None, timeout=None):
            llamadas.append((url, json))
            return _Respuesta(200, {"ok": True})

        monkeypatch.setattr(avisos_telegram.requests, "post", fake_post)
        ok, error = avisos_telegram.enviar("TOKEN", "@canal", "hola", sin_sonido=True)
        assert ok and error == ""
        url, payload = llamadas[0]
        assert url == "https://api.telegram.org/botTOKEN/sendMessage"
        assert payload["chat_id"] == "@canal" and payload["parse_mode"] == "HTML"
        assert payload["disable_notification"] is True

    def test_error_de_telegram_no_filtra_el_token(self, monkeypatch):
        monkeypatch.setattr(
            avisos_telegram.requests, "post",
            lambda url, json=None, timeout=None: _Respuesta(403, {"ok": False, "description": "Forbidden: bot is not a member of the channel chat"}),
        )
        ok, error = avisos_telegram.enviar("TOKEN-SECRETO", "@canal", "hola", sin_sonido=False)
        assert not ok
        assert "bot is not a member" in error
        assert "TOKEN-SECRETO" not in error

    def test_fallo_de_red_no_filtra_el_token(self, monkeypatch):
        def fake_post(url, json=None, timeout=None):
            raise avisos_telegram.requests.ConnectionError(f"fallo conectando a {url}")

        monkeypatch.setattr(avisos_telegram.requests, "post", fake_post)
        ok, error = avisos_telegram.enviar("TOKEN-SECRETO", "@canal", "hola", sin_sonido=False)
        assert not ok
        assert "TOKEN-SECRETO" not in error


class TestTopeDiario:

    def _preparar(self, tmp_path, monkeypatch, enviados):
        import json as _json
        from datetime import datetime
        from zoneinfo import ZoneInfo
        hoy = datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
        minimos_path = tmp_path / "minimos.json"
        enviados_path = tmp_path / "avisos_enviados.json"
        minimos_path.write_text(_json.dumps({
            "ofertas_url": "https://stackfit.es/ofertas/",
            "minimos": [_minimo(pid=f"p{i}-1kg-hsn", fecha=hoy) for i in range(5)],
        }), encoding="utf-8")
        enviados_path.write_text(_json.dumps({
            "enviados": [{"id": e, "tienda": "HSN", "precio": 39.9, "fecha": hoy} for e in enviados],
        }), encoding="utf-8")
        monkeypatch.setattr(avisos_telegram, "MINIMOS_PATH", str(minimos_path))
        monkeypatch.setattr(avisos_telegram, "ENVIADOS_PATH", str(enviados_path))
        monkeypatch.setattr(avisos_telegram.time, "sleep", lambda s: None)
        monkeypatch.setattr(sys, "argv", ["avisos_telegram.py"])
        publicados = []
        monkeypatch.setattr(
            avisos_telegram, "enviar",
            lambda token, chat, texto, sin_sonido: (publicados.append(texto), (True, ""))[1],
        )
        return enviados_path, publicados

    def test_publica_como_mucho_tres_y_guarda_el_estado(self, tmp_path, monkeypatch):
        import json as _json
        enviados_path, publicados = self._preparar(tmp_path, monkeypatch, enviados=[])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "@canal")
        assert avisos_telegram.main() == 0
        assert len(publicados) == 3
        assert "otros 2 productos" in publicados[-1]
        assert len(_json.loads(enviados_path.read_text(encoding="utf-8"))["enviados"]) == 3

    def test_segunda_ejecucion_del_dia_no_publica_mas(self, tmp_path, monkeypatch):
        _, publicados = self._preparar(tmp_path, monkeypatch, enviados=["p0-1kg-hsn", "p1-1kg-hsn", "p2-1kg-hsn"])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "@canal")
        assert avisos_telegram.main() == 0
        assert publicados == []

    def test_sin_token_no_publica_ni_toca_el_estado(self, tmp_path, monkeypatch):
        import json as _json
        enviados_path, publicados = self._preparar(tmp_path, monkeypatch, enviados=[])
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        assert avisos_telegram.main() == 0
        assert publicados == []
        assert _json.loads(enviados_path.read_text(encoding="utf-8"))["enviados"] == []

    def test_si_telegram_falla_sale_con_error_y_no_marca_como_enviado(self, tmp_path, monkeypatch):
        import json as _json
        enviados_path, _ = self._preparar(tmp_path, monkeypatch, enviados=[])
        monkeypatch.setattr(avisos_telegram, "enviar", lambda *a, **k: (False, "403: Forbidden"))
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "@canal")
        assert avisos_telegram.main() == 1
        assert _json.loads(enviados_path.read_text(encoding="utf-8"))["enviados"] == []
