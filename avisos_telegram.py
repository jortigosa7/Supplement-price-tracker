"""
avisos_telegram.py — publica en el canal de Telegram los mínimos reales de hoy.

Lee data/minimos.json (lo genera build.py) y publica los que todavía no se han
avisado. Lo que ya se envió queda en data/avisos_enviados.json para no repetir.

Uso:
    python avisos_telegram.py             # publica si hay token; si no, solo enseña los mensajes
    python avisos_telegram.py --dry-run   # nunca publica, solo enseña los mensajes

Variables de entorno (secrets del repo en GitHub Actions):
    TELEGRAM_BOT_TOKEN   token del bot que da @BotFather
    TELEGRAM_CHAT_ID     canal donde publica, p. ej. @nombre_del_canal (el bot tiene que ser admin)

Sale con código 1 solo si Telegram rechaza algún envío. Sin token o sin nada
nuevo que avisar sale con 0: no es un fallo.
"""

import html
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = "data"
MINIMOS_PATH = os.path.join(DATA_DIR, "minimos.json")
ENVIADOS_PATH = os.path.join(DATA_DIR, "avisos_enviados.json")

MAX_AVISOS_POR_DIA = 3         # más de esto y la gente silencia el canal (la web promete este tope)
REPETIR_TRAS_DIAS = 21         # no se repite un producto antes, salvo que baje todavía más
BAJADA_PARA_REPETIR = 0.03     # ...al menos un 3 % por debajo del precio ya avisado
MAX_ANTIGUEDAD_DIAS = 1        # no se avisa de precios de un scrape de hace más de un día
CONSERVAR_DIAS = 180           # historial de envíos que se guarda
HORA_SIN_SONIDO = 8            # antes de esta hora (Madrid) el aviso llega sin notificación sonora


def _eur(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


def cargar_json(path: str, por_defecto):
    if not os.path.exists(path):
        return por_defecto
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seleccionar_nuevos(minimos: list[dict], enviados: list[dict], hoy: date) -> list[dict]:
    """Mínimos que no se han avisado ya (o que han bajado bastante desde el último aviso)."""
    ultimo: dict[tuple, dict] = {}
    for e in enviados:
        clave = (e["id"], e["tienda"])
        if clave not in ultimo or e["fecha"] > ultimo[clave]["fecha"]:
            ultimo[clave] = e

    nuevos = []
    for m in minimos:
        previo = ultimo.get((m["id"], m["tienda"]))
        if previo:
            dias = (hoy - date.fromisoformat(previo["fecha"])).days
            ha_bajado = m["precio"] <= previo["precio"] * (1 - BAJADA_PARA_REPETIR)
            if dias < REPETIR_TRAS_DIAS and not ha_bajado:
                continue
        nuevos.append(m)
    return nuevos


def formatear_aviso(m: dict, pendientes: int = 0, ofertas_url: str = "") -> str:
    """Texto del aviso en HTML de Telegram."""
    nombre = html.escape(m["nombre"])
    tienda = html.escape(m["tienda"])
    sello = (
        f"Precio más bajo en {m['dias_historial']} días"
        if m.get("es_record")
        else f"Iguala su mínimo de {m['dias_historial']} días"
    )
    lineas = [
        f"<b>{nombre}</b> · {tienda}",
        f"<b>{_eur(m['precio'])} €</b>  (suele costar {_eur(m['precio_habitual'])} €, −{round(m['rebaja_pct'])} %)",
        sello + (f" · {_eur(m['precio_por_kg'])} €/kg" if m.get("precio_por_kg") else ""),
    ]
    if m.get("puesto_texto"):
        lineas.append(f"Con esta rebaja es {html.escape(m['puesto_texto'])}")
    lineas.append("")
    enlaces = [f'<a href="{html.escape(m["url_afiliado"], quote=True)}">Ver en {tienda}</a>']
    if m.get("pagina_url_abs"):
        enlaces.append(f'<a href="{html.escape(m["pagina_url_abs"], quote=True)}">Historial de precios</a>')
    lineas.append(" · ".join(enlaces))
    lineas.append("<i>Enlace de afiliado: si compras, StackFit se lleva una comisión y a ti no te cuesta más.</i>")
    if pendientes > 0 and ofertas_url:
        otros = "otro producto" if pendientes == 1 else f"otros {pendientes} productos"
        lineas += ["", f'Hoy hay {otros} en mínimos: <a href="{html.escape(ofertas_url, quote=True)}">verlos todos</a>']
    return "\n".join(lineas)


def enviar(token: str, chat_id: str, texto: str, sin_sonido: bool) -> tuple[bool, str]:
    """Publica un mensaje. Devuelve (ok, descripción del error). Nunca imprime el token."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_notification": sin_sonido,
    }
    for intento in range(2):
        try:
            r = requests.post(url, json=payload, timeout=20)
            cuerpo = r.json()
        except (requests.RequestException, ValueError) as exc:
            return False, f"sin respuesta de Telegram ({type(exc).__name__})"
        if cuerpo.get("ok"):
            return True, ""
        espera = (cuerpo.get("parameters") or {}).get("retry_after")
        if r.status_code == 429 and espera and intento == 0:
            time.sleep(min(int(espera), 30) + 1)
            continue
        return False, f"{r.status_code}: {cuerpo.get('description', 'error desconocido')}"
    return False, "demasiadas peticiones"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    publicar = bool(token and chat_id) and not dry_run

    datos = cargar_json(MINIMOS_PATH, None)
    if not datos:
        print(f"No existe {MINIMOS_PATH}: ejecuta antes build.py.")
        return 0
    estado = cargar_json(ENVIADOS_PATH, {"enviados": []})
    enviados = estado.get("enviados", [])

    hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
    minimos = datos.get("minimos", [])
    if publicar:
        frescos = [m for m in minimos if (hoy - date.fromisoformat(m["fecha"])).days <= MAX_ANTIGUEDAD_DIAS]
        if len(frescos) < len(minimos):
            print(f"Se descartan {len(minimos) - len(frescos)} mínimos con precio de hace más de {MAX_ANTIGUEDAD_DIAS} día(s).")
        minimos = frescos

    nuevos = seleccionar_nuevos(minimos, enviados, hoy)
    # El tope es diario: si el workflow se lanza dos veces el mismo día, no se duplica el cupo
    ya_hoy = sum(1 for e in enviados if e["fecha"] == hoy.isoformat())
    a_enviar = nuevos[:max(0, MAX_AVISOS_POR_DIA - ya_hoy)]
    # Lo que queda en la web además de lo que se publica ahora
    resto = len(minimos) - len(a_enviar)
    print(f"Mínimos hoy: {len(minimos)} | sin avisar: {len(nuevos)} | se publican: {len(a_enviar)}")

    if not a_enviar:
        return 0
    if not publicar:
        motivo = "--dry-run" if dry_run else "faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
        print(f"MODO PRUEBA ({motivo}): no se publica nada.\n")

    sin_sonido = datetime.now(ZoneInfo("Europe/Madrid")).hour < HORA_SIN_SONIDO
    fallos = 0
    for i, m in enumerate(a_enviar):
        es_ultimo = i == len(a_enviar) - 1
        texto = formatear_aviso(m, pendientes=resto if es_ultimo else 0, ofertas_url=datos.get("ofertas_url", ""))
        if not publicar:
            print(texto + "\n" + "-" * 40)
            continue
        ok, error = enviar(token, chat_id, texto, sin_sonido)
        if ok:
            enviados.append({"id": m["id"], "tienda": m["tienda"], "precio": m["precio"], "fecha": hoy.isoformat()})
            print(f"  publicado: {m['nombre']} ({_eur(m['precio'])} €)")
            time.sleep(1.5)
        else:
            fallos += 1
            print(f"  ERROR al publicar {m['nombre']}: {error}")

    if publicar:
        corte = (hoy - timedelta(days=CONSERVAR_DIAS)).isoformat()
        estado["enviados"] = [e for e in enviados if e["fecha"] >= corte]
        with open(ENVIADOS_PATH, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
