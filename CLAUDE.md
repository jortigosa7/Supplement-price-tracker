# CLAUDE.md — StackFit

Este fichero te da el contexto que necesitas para trabajar en este repo sin que Javier te lo tenga que explicar cada vez. Léelo entero antes de tu primer cambio en una sesión nueva.

## Qué es

StackFit (https://stackfit.es) es un comparador de precios de suplementos deportivos para el mercado español. Normaliza todos los precios a **€/kg** para que el usuario vea cuál es la opción realmente más barata. Está pensado como sitio estático generado, sin backend ni base de datos en producción.

- Repo: `jortigosa7/Supplement-price-tracker`
- Dominio: stackfit.es (GitHub Pages, sirviendo `docs/`)
- Autor: Javier Ortigosa, primer año Ingeniería Matemática en UFV, ~6 meses de programación
- Estado: en producción pero pre-tracción, todavía iterando

## Arquitectura

```
scrapers/        → Playwright (Prozis) + requests/BeautifulSoup (HSN, MyProtein, Nutritienda)
   ↓
data/products.json    (output normalizado a €/kg, schema flexible)
   ↓
build.py         → Jinja2 templates → docs/
   ↓
docs/            → GitHub Pages
```

Stack: Python 3 + Playwright + BeautifulSoup + Jinja2 + vanilla JS en frontend. No hay React, no hay Node en build, no hay framework. **Mantén esto.** Cualquier propuesta de "vamos a meter Next.js / Astro / Vue" se rechaza salvo que Javier lo pida explícitamente.

### Tiendas cubiertas

HSN, MyProtein, Prozis, Nutritienda.

### Categorías cubiertas

Whey protein, creatina, BCAA, pre-entreno. Todo normalizado a €/kg.

### Páginas generadas

- Home con filtros
- ~240 páginas de comparación en `/comparar/<producto-vs-producto>/`
- Recomendador tipo quiz en `/test/`
- JSON-LD schema markup en todas

## Convenciones de código

- **Nombres**: variables y funciones en inglés, contenido/textos de UI en español.
- **Python**: estilo PEP 8 razonable, sin black agresivo. No reformatees ficheros enteros sin pedir.
- **Imports**: stdlib → terceros → locales, ordenados.
- **Logging**: usa `print` para scrapers (es scrappy y está bien), `logging` solo si Javier lo introduce.
- **Tipado**: no uses type hints exhaustivos. Hints solo en funciones públicas o donde aclaren algo de verdad.
- **Comentarios**: en español, solo cuando el código no se explica solo. No comentes lo obvio.
- **Commits**: mensajes en español, presente, imperativo. Ejemplo: "arregla selector de HSN para BCAA".

## Frontend

- Tema oscuro con acento lima `#c8ff4d`.
- Fuentes: DM Sans (cuerpo) + Instrument Serif (display). Había una iteración previa con Syne; si ves Syne en algún sitio, pregunta antes de cambiar.
- Vanilla JS, sin frameworks. CSS plano, sin Tailwind (a no ser que Javier lo pida).
- Móvil first: la mayoría del tráfico esperado es móvil.

## Estado actual

### Funciona

- Build estático completo y desplegado.
- Scrapers de MyProtein y Nutritienda.
- Sistema de filtros y comparador.
- Quiz recomendador.
- Afiliación HSN activa (ID `JORTIGOSA`) — los enlaces ya van con afiliado.
- Tag de Amazon `suplemento0f1-21` activo (requiere ventas para mantenerse).
- Google Search Console configurado, indexación en fase temprana.

### Roto o pendiente

- **Scrapers HSN y Prozis**: selectores rotos, los sitios cambiaron HTML. Prioridad alta.
- **GitHub Actions**: el job de scrape enriquecido se queda sin tiempo, hay que subir el timeout.
- **`añadir_afiliados.py`**: staged y listo, usa variables de entorno de Awin. Bloqueado por aprobación de Awin para MyProtein, Prozis y Nutritienda. Cuando lleguen aprobaciones: rellenar `.env` con los IDs y correr el script.
- **MyProtein**: la solicitud Awin fue rechazada una vez. Reintentar más adelante u outreach directo.

### Decisiones tomadas que no se revisan sin pedir

- Stack estático (no migrar a SSR/SPA).
- Cuatro tiendas iniciales — no añadir tiendas nuevas hasta estabilizar tráfico y scrapers actuales.
- Categoría perfumes / cualquier comparador paralelo: **no**. Ya se descartó.

## Pending / ideas en la nevera

- Proyecto paralelo de estadísticas de fútbol como práctica de análisis de datos (independiente de StackFit, en el mismo perfil de GitHub o repo aparte).
- Histórico de precios agregado como ángulo de prensa para outreach (ver más abajo).
- Reactivar OAuth de `get_token.py` en el proyecto del blog `musculoresultados.blogspot.com` (n8n + Groq + Blogger API), bloqueado por refresco de token.

## outreach/

Carpeta nueva con automatización de outreach a creadores y medios fitness españoles. Genera drafts personalizados con Groq usando datos de `data/products.json`, los deja en `outreach/borradores/` para que Javier los revise antes de enviar.

Subcomandos: `drafts`, `followup`, `status`, `mark`. Ver `outreach/README.md`.

Si trabajas aquí: **nunca añadas envío automático real sin pedir.** El diseño es deliberadamente "human in the loop".

## Cómo trabaja Javier

- Comunicación en **español**, tono directo y casual, sin floritura literaria.
- Respuestas **breves y aterrizadas**. Nada de "¡Qué pregunta tan interesante!" ni preámbulos.
- Empuja propuestas concretas. Si una idea tiene un trade-off real, dilo claro antes de implementar.
- Está aprendiendo. Cuando hagas algo no trivial, explica **por qué** brevemente, no solo el qué.
- Le interesa Data Science / ML como salida profesional. Si un cambio se cruza con eso (análisis de datos del propio catálogo, modelos, etc.), márcalo.
- Está en exámenes de Cálculo II ahora mismo (mayo 2026). No es contexto del repo pero puede afectar disponibilidad / ritmo de revisión.

## Antes de hacer cambios grandes

1. Lee la sección **Decisiones tomadas que no se revisan**.
2. Si el cambio toca scrapers, prueba localmente con un solo producto antes de tocar la suite.
3. Si toca `build.py` o templates, corre el build completo y revisa que `docs/` siga teniendo las ~240 páginas de comparación.
4. Si toca afiliación, **no toques los IDs activos** sin confirmación explícita.

## Comandos típicos

```bash
# Build local
python build.py

# Correr un scraper individual
python scrapers/hsn.py

# Servir docs/ local para revisar
python -m http.server 8000 -d docs

# Outreach
cd outreach && python outreach.py status
```
