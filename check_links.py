"""
check_links.py — Comprueba que las URLs de tienda en products.json responden.

Sale con código 0 si todo está bien o si solo hay 429/3xx (no son errores reales).
Sale con código 1 si hay algún 404 real → el workflow de GitHub Actions fallará
y mandará email de notificación.

Uso:
    python check_links.py [--store hsn] [--verbose]

Opciones:
    --store NAME   Solo comprobar una tienda concreta (hsn, myprotein, prozis, nutritienda)
    --verbose      Mostrar también las URLs que responden 200
"""

import argparse
import base64
import json
import os
import re
import sys
import time

# Forzar UTF-8 en stdout (necesario en Windows con cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import urllib.error
import urllib.request

DATA_FILE = "data/products.json"
DELAY     = 0.4   # segundos entre peticiones (general)
DELAY_PROZIS = 1.2  # Prozis necesita más pausa para no recibir 429

# Cabeceras de navegador real — necesarias para Prozis (devuelve 429 sin ellas)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def decode_hsn_url(aff_url: str) -> str:
    """Extrae la URL real del enlace de afiliado de HSN (base64 codificado)."""
    try:
        m = re.search(r"linkid=([A-Za-z0-9+/=]+)", aff_url)
        if not m:
            return aff_url
        decoded = base64.b64decode(m.group(1)).decode()
        parts = decoded.split("||")
        if len(parts) >= 3:
            return parts[-1]
    except Exception:
        pass
    return aff_url


def cargar_urls(solo_tienda: str | None = None) -> list[dict]:
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    urls = []
    for p in data["products"]:
        for pr in p.get("precios", []):
            tienda = pr.get("tienda", "?")
            if solo_tienda and tienda.lower() != solo_tienda.lower():
                continue
            url_afiliado = pr.get("url_afiliado", "")
            if not url_afiliado:
                continue
            # Para HSN, decodificar el enlace de afiliado para obtener la URL real
            real_url = decode_hsn_url(url_afiliado) if tienda == "HSN" else url_afiliado
            urls.append({
                "tienda": tienda,
                "prod":   p.get("nombre_normalizado", "?")[:60],
                "url":    real_url,
            })
    return urls


def comprobar_url(url: str, tienda: str) -> tuple[int | str, str]:
    """
    Devuelve (codigo, location_o_vacio).
    codigo puede ser int (HTTP status) o string de error ("TIMEOUT", "CONNECTION", etc.)
    Para redirecciones, location contiene la URL destino.
    """
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None  # no seguir la redirección

    try:
        req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=10) as resp:
            return resp.getcode(), ""
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "") if e.code in (301, 302, 303, 307, 308) else ""
        return e.code, loc
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower():
            return "TIMEOUT", ""
        return "CONNECTION", reason[:60]
    except Exception as e:
        return "ERROR", str(e)[:60]


def main():
    parser = argparse.ArgumentParser(description="Comprueba URLs de tienda en products.json")
    parser.add_argument("--store", help="Solo comprobar esta tienda")
    parser.add_argument("--verbose", action="store_true", help="Mostrar URLs OK también")
    args = parser.parse_args()

    urls = cargar_urls(args.store)
    total = len(urls)
    print(f"Comprobando {total} URLs{f' de {args.store}' if args.store else ''}...")

    resultados = {"ok": [], "redir": [], "not_found": [], "rate_limit": [], "error": []}

    for i, item in enumerate(urls):
        tienda = item["tienda"]
        codigo, location = comprobar_url(item["url"], tienda)

        if codigo == 200:
            resultados["ok"].append(item)
            if args.verbose:
                print(f"  OK   [{tienda}] {item['prod']}")
        elif isinstance(codigo, int) and codigo in (301, 302, 303, 307, 308):
            resultados["redir"].append({**item, "codigo": codigo, "location": location})
            print(f"  {codigo}  [{tienda}] {item['prod'][:45]} → {location[:55]}")
        elif codigo == 404:
            resultados["not_found"].append({**item, "codigo": 404})
            print(f"  404  [{tienda}] {item['prod']}")
            print(f"       {item['url']}")
        elif codigo == 429:
            resultados["rate_limit"].append({**item, "codigo": 429})
            print(f"  429  [{tienda}] {item['prod']} (rate limit, no es error)")
        else:
            resultados["error"].append({**item, "codigo": codigo, "detalle": location})
            print(f"  ERR  [{tienda}] {item['prod']} — {codigo}: {location}")

        # Pausa adaptada por tienda
        delay = DELAY_PROZIS if tienda == "Prozis" else DELAY
        if i < total - 1:
            time.sleep(delay)

    # ── Resumen ──────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  OK            : {len(resultados['ok'])}")
    print(f"  Redirecciones : {len(resultados['redir'])}  (no crítico)")
    print(f"  Rate limit    : {len(resultados['rate_limit'])}  (no crítico, es Prozis)")
    print(f"  404 reales    : {len(resultados['not_found'])}  ← crítico")
    print(f"  Otros errores : {len(resultados['error'])}")
    print("=" * 60)

    if resultados["redir"]:
        print("\nRedirecciones (URLs obsoletas en products.json):")
        for x in resultados["redir"]:
            print(f"  [{x['tienda']}] {x['prod'][:45]:45s} → {x['location'][:50]}")

    if resultados["not_found"]:
        print("\n[CRITICO] URLs con 404 — el botón de compra lleva a una página rota:")
        for x in resultados["not_found"]:
            print(f"  [{x['tienda']}] {x['prod']}")
            print(f"  {x['url']}")
        print()
        print("Esto es un error real. Revisar y corregir en data/products.json")
        print("o deshabilitar el botón de compra para estos productos.")
        sys.exit(1)  # el workflow falla → GitHub manda email

    if resultados["error"]:
        print("\nErrores de red (puede ser transitorio):")
        for x in resultados["error"]:
            print(f"  [{x['tienda']}] {x['prod']} — {x['codigo']}: {x['detalle']}")
        # Los errores de red no hacen fallar el workflow (pueden ser transitorios)

    print("\nSin 404 reales. Todo OK.")


if __name__ == "__main__":
    main()
