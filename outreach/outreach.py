"""
StackFit outreach automation.

Uso:
    python outreach.py drafts     # genera drafts para contactos pendientes
    python outreach.py followup   # genera follow-ups para enviados sin respuesta >7d
    python outreach.py status     # muestra resumen del pipeline
    python outreach.py mark <id> <estado>   # marca estado manual

Estados: pending_review | sent | replied | declined | followup_sent
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"
PRODUCTS_PATHS = ["../data/products.json", "data/products.json", "products.json"]
STATE_FILE = "outreach.json"
CONTACTS_FILE = "contactos.csv"
DRAFTS_DIR = Path("borradores")
FOLLOWUP_DIR = Path("followups")
FOLLOWUP_DAYS = 7


# ---------- utilidades de estado ----------

def load_state():
    if Path(STATE_FILE).exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def contact_id(nombre):
    import unicodedata
    s = unicodedata.normalize("NFKD", nombre)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(" ", "_").replace("'", "").replace("ñ", "n")


# ---------- resumen de products.json ----------

def load_products_summary():
    """Carga products.json y devuelve un resumen en texto para el prompt.
    Es flexible al schema: si no reconoce campos, devuelve un fallback genérico.
    """
    products = None
    for p in PRODUCTS_PATHS:
        if Path(p).exists():
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
                products = raw.get("products") if isinstance(raw, dict) else raw
            break

    if not products:
        return (
            "Comparador StackFit con productos de HSN, MyProtein, Prozis y "
            "Nutritienda en categorías proteína whey, creatina, BCAA y "
            "pre-entreno, todos normalizados a €/kg."
        )

    try:
        n = len(products)
        stores = set()
        cats = {}
        for prod in products:
            store = prod.get("tienda_mas_barata") or prod.get("store") or prod.get("tienda")
            cat = prod.get("categoria_display") or prod.get("categoria") or prod.get("category")
            price_kg = prod.get("precio_por_kg_min") or prod.get("price_per_kg") or prod.get("eur_por_kg")
            if store:
                stores.add(store)
            if cat and price_kg:
                cats.setdefault(cat, []).append((store, price_kg))

        cheapest = {}
        for cat, items in cats.items():
            valid = [(s, p) for s, p in items if isinstance(p, (int, float)) and p > 0]
            if valid:
                s, p = min(valid, key=lambda x: x[1])
                cheapest[cat] = (s, p)

        lines = [
            f"Catálogo actual: {n} productos en {len(stores)} tiendas ({', '.join(sorted(stores))})."
        ]
        if cheapest:
            lines.append("Tiendas más baratas por categoría (€/kg):")
            for cat, (s, p) in cheapest.items():
                lines.append(f"  - {cat}: {s} a {p:.2f} €/kg")
        return "\n".join(lines)

    except Exception as e:
        return f"Catálogo con {len(products)} productos (resumen automático falló: {e})."


# ---------- llamada a Groq ----------

def call_groq(prompt, temperature=0.7, max_tokens=600):
    if not GROQ_API_KEY:
        raise RuntimeError("Falta GROQ_API_KEY en .env")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ---------- prompts ----------

PROMPT_INITIAL = """Eres copywriter de outreach para creadores y medios fitness en España.
Vas a escribir un email corto y personalizado de parte de Javier, creador de StackFit (stackfit.es), un comparador de precios de suplementos deportivos en España (proteína, creatina, BCAA, pre-entreno) que normaliza todo a €/kg para que el usuario vea cuál es la opción más barata real.

Datos del catálogo de StackFit que puedes usar si encajan con el ángulo:
{data_summary}

Destinatario: {nombre}
Su blog/canal: {blog}
Tier: {tier}
Ángulo concreto para este contacto: {angulo}

REGLAS DURAS:
- Máximo 130 palabras en el body
- Tutea, tono casual pero profesional
- Subject corto (máx 8 palabras), sin clickbait ni emojis
- Primera frase: referencia concreta a SU contenido. Si no hay info suficiente, escribe literalmente "[REF: añadir referencia concreta a un post/vídeo suyo]" para que Javier la rellene
- Una sola petición clara al final (NO listas de cosas)
- Prohibido: "sinergia", "win-win", "valor añadido", "no quiero robarte tiempo", "espero que estés bien"
- NO menciones que es estudiante salvo que el ángulo lo pida
- Si tienes datos concretos del catálogo arriba, incrústalos como gancho (ej: "la creatina más barata en España ahora mismo está a X €/kg en Z")
- Firma: "Javier — StackFit"

Devuelve SOLO en este formato exacto, nada más:
SUBJECT: <asunto>
BODY:
<cuerpo>
"""

PROMPT_FOLLOWUP = """Escribe un follow-up de 1 párrafo (máx 60 palabras) en español, tuteando, para reenganchar a {nombre} ({blog}) sobre el email anterior de Javier de StackFit. Han pasado {dias} días sin respuesta.

Reglas:
- NO empieces con "Hola de nuevo" ni "Solo quería"
- Añade UN dato nuevo, gancho o ángulo distinto al primero
- Cierra con una pregunta sí/no fácil de contestar
- Firma: "Javier"

Devuelve SOLO:
SUBJECT: Re: <asunto original o tema corto>
BODY:
<cuerpo>
"""


# ---------- comandos ----------

def cmd_drafts(args):
    DRAFTS_DIR.mkdir(exist_ok=True)
    state = load_state()
    data_summary = load_products_summary()
    print(f"Resumen de datos:\n{data_summary}\n")

    with open(CONTACTS_FILE, encoding="utf-8") as f:
        contactos = list(csv.DictReader(f))

    generated = 0
    for c in contactos:
        cid = contact_id(c["nombre"])
        if cid in state and state[cid].get("status") not in (None, ""):
            print(f"[skip] {c['nombre']}: ya en estado '{state[cid]['status']}'")
            continue

        print(f"[gen]  {c['nombre']}...", end=" ", flush=True)
        prompt = PROMPT_INITIAL.format(
            data_summary=data_summary,
            nombre=c["nombre"],
            blog=c["blog_o_canal"],
            tier=c.get("tier", "?"),
            angulo=c["angulo"],
        )
        try:
            draft = call_groq(prompt)
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        fname = DRAFTS_DIR / f"{cid}.md"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"# {c['nombre']} - {c['blog_o_canal']}\n\n")
            f.write(f"- **Contacto:** {c['contacto']}\n")
            f.write(f"- **Tier:** {c.get('tier', '?')}\n")
            f.write(f"- **Angulo:** {c['angulo']}\n\n---\n\n")
            f.write(draft)

        state[cid] = {
            "nombre": c["nombre"],
            "blog": c["blog_o_canal"],
            "contacto": c["contacto"],
            "tier": c.get("tier", "?"),
            "draft_file": str(fname),
            "draft_generated_at": datetime.now().isoformat(timespec="seconds"),
            "status": "pending_review",
        }
        save_state(state)
        generated += 1
        print("OK")

    print(f"\n{generated} drafts nuevos en {DRAFTS_DIR}/")


def cmd_followup(args):
    FOLLOWUP_DIR.mkdir(exist_ok=True)
    state = load_state()
    cutoff = datetime.now() - timedelta(days=FOLLOWUP_DAYS)

    generated = 0
    for cid, info in state.items():
        if info.get("status") != "sent":
            continue
        sent_at = info.get("sent_at")
        if not sent_at:
            continue
        if datetime.fromisoformat(sent_at) > cutoff:
            continue
        if info.get("followup_generated_at"):
            continue

        dias = (datetime.now() - datetime.fromisoformat(sent_at)).days
        print(f"[follow] {info['nombre']} ({dias}d)...", end=" ", flush=True)
        prompt = PROMPT_FOLLOWUP.format(
            nombre=info["nombre"], blog=info["blog"], dias=dias
        )
        try:
            draft = call_groq(prompt, temperature=0.6, max_tokens=300)
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        fname = FOLLOWUP_DIR / f"{cid}_followup.md"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"# Follow-up: {info['nombre']}\n\n")
            f.write(f"Enviado original: {sent_at} ({dias} dias)\n\n---\n\n")
            f.write(draft)

        info["followup_file"] = str(fname)
        info["followup_generated_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        generated += 1
        print("OK")

    print(f"\n{generated} follow-ups generados en {FOLLOWUP_DIR}/")


def cmd_status(args):
    state = load_state()
    if not state:
        print("Sin contactos aun. Corre: python outreach.py drafts")
        return

    counts = {}
    for info in state.values():
        s = info.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    print("Pipeline:")
    for s, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"   {s:20s} {n}")

    print("\nDetalle:")
    rows = sorted(state.items(), key=lambda x: x[1].get("status", ""))
    for cid, info in rows:
        print(f"   {cid:30s} {info.get('status', '?'):16s} {info['blog']}")


def cmd_mark(args):
    state = load_state()
    cid, estado = args.id, args.estado
    if cid not in state:
        print(f"ERROR: no existe '{cid}'. Disponibles:")
        for k in state:
            print(f"   {k}")
        sys.exit(1)
    state[cid]["status"] = estado
    if estado == "sent":
        state[cid]["sent_at"] = datetime.now().isoformat(timespec="seconds")
    elif estado == "replied":
        state[cid]["replied_at"] = datetime.now().isoformat(timespec="seconds")
    elif estado == "followup_sent":
        state[cid]["followup_sent_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    print(f"OK: {cid} -> {estado}")


def main():
    parser = argparse.ArgumentParser(description="Outreach automation para StackFit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("drafts", help="Genera drafts iniciales")
    sub.add_parser("followup", help="Genera follow-ups para enviados sin respuesta")
    sub.add_parser("status", help="Muestra pipeline")

    p_mark = sub.add_parser("mark", help="Marca estado manual")
    p_mark.add_argument("id", help="ID del contacto (snake_case del nombre)")
    p_mark.add_argument("estado", choices=["pending_review", "sent", "replied", "declined", "followup_sent"])

    args = parser.parse_args()
    {"drafts": cmd_drafts, "followup": cmd_followup, "status": cmd_status, "mark": cmd_mark}[args.cmd](args)


if __name__ == "__main__":
    main()
