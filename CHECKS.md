# CHECKS.md — Guía de verificaciones post-build de StackFit

`build.py` corre automáticamente una batería de checks al final de cada build.
Si falla alguno, el build para con `sys.exit(1)` y GitHub Actions manda email con el mensaje completo.
Las métricas de cada build exitoso se guardan en `data/build_stats.json`.

---

## Resumen de checks

| # | Qué detecta | Umbral / condición |
|---|------------|-------------------|
| 1 | Destino de redirección no existe en `docs/`, o es a su vez una redirección (cadena) | cualquier caso |
| 2 | Enlace interno absoluto en un HTML que apunta a ruta inexistente | cualquier caso |
| 3 | Tienda con 0 productos, o con >30% menos que el build anterior | 0 prod. o −30% |
| 4 | Comparaciones, grupos multi-tienda o páginas de sitemap que bajan | cualquier bajada |
| 5 | ID en `comparaciones.json` que no existe en `products.json` | cualquier caso |
| 6 | "Desconocida" en texto visible de una página, o campo crítico vacío en un producto | cualquier caso |
| 7 | €/kg > 10× la mediana de su categoría (valor absurdo hacia arriba) | >10× mediana |
| 7b| €/kg < 10% de la mediana (valor absurdo hacia abajo) — en `build.py` | <10% mediana |
| 7c| Bajada de precio >40% de golpe respecto al build anterior — en `build.py` | >40% bajada |
| 8 | >10% de IDs del catálogo desaparecen entre builds (posible cambio de formato) | >10% del catálogo |

Los checks 5, 7b y 7c están implementados directamente en `build.py`.
Los checks 1–4, 6, 7 y 8 están en `checks.py`.

---

## Qué hacer cuando salta cada check

### CHECK 1 — Redirección rota o en cadena

**Aparece cuando**: `data/redirecciones.json` tiene una entrada cuyo campo `hasta` apunta
a una URL que ya no existe en `docs/`, o que es a su vez otra redirección.

**Cómo reproducir el problema**: corre `build.py` localmente. El error dice exactamente
`desde` y `hasta` de la entrada problemática.

**Soluciones**:
- **Destino inexistente**: o el `slug_publico` del producto cambió (busca el nuevo en `products.json`)
  y actualiza `redirecciones.json`, o la comparación fue eliminada de `comparaciones.json`
  (en ese caso cambia `hasta` a `/comparar/`).
- **Cadena**: el destino en `hasta` es él mismo una fuente en `redirecciones.json`. Apunta
  directamente al destino final.

---

### CHECK 2 — Enlace interno roto

**Aparece cuando**: un `<a href="/ruta/">` en algún HTML de `docs/` apunta a una ruta
que no existe en `docs/`.

**Causas frecuentes**:
- Un slug de comparación cambió pero el template sigue usando el viejo.
- Se generó un enlace a una página de categoría que no existe.

**Solución**: el error indica exactamente qué archivo HTML y qué `href` está roto.
Busca en `templates/` de dónde viene ese enlace y actualízalo.

---

### CHECK 3 — Tienda con 0 o muchos menos productos

**Aparece cuando**: una tienda devuelve 0 productos, o más de un 30% menos que el build anterior.

**Causas frecuentes**:
- El scraper está roto (la tienda cambió su HTML o estructura JSON-LD).
- El cap `MAX_POR_CATEGORIA` de Nutritienda es demasiado bajo.
- Una categoría devolvió 0 (timeout, bloqueo temporal, etc.).

**Solución**:
1. Corre el scraper de la tienda en cuestión manualmente: `python scrapers/<tienda>.py`.
2. Si falla, revisa el selector o el JSON-LD de la página de listado.
3. Si fue temporal (timeout), vuelve a correr el build.

---

### CHECK 4 — Comparaciones, grupos o sitemap que bajan

**Aparece cuando**: el número de comparaciones generadas, grupos multi-tienda, o páginas
en el sitemap es menor que en el build anterior.

**Causas frecuentes**:
- Se eliminó un par de `comparaciones.json` sin querer.
- Un producto que aparecía en varias comparaciones dejó de scrapear.
- La lógica de matching cambió y un grupo multi-tienda desapareció.

**Solución**: compara el build actual con el anterior en `data/build_stats.json` para
ver qué métrica bajó. Si es intencionado (borraste un par), el nuevo número pasará
a ser la nueva base tras el siguiente build exitoso.

---

### CHECK 5 — ID en comparaciones.json no existe en products.json

**Aparece cuando**: un `id_a` o `id_b` en `data/comparaciones.json` no se encuentra
en el catálogo de productos del build actual.

**Causas frecuentes**:
- El scraper dejó de encontrar ese producto (descatalogado, URL cambiada).
- El ID del producto cambió (marca resuelta diferente, peso extraído distinto).

**Solución**:
- Busca el producto por nombre en `data/products.json`.
- Si existe con un ID diferente, actualiza `comparaciones.json`.
- Si ya no existe en ninguna tienda, mueve el par a "pares irrecuperables" en `comparaciones.json`
  y añade una redirección en `redirecciones.json` hacia `/comparar/`.

---

### CHECK 6 — "Desconocida" visible o campo vacío

**Aparece cuando**:
- El texto visible de alguna página contiene la palabra "desconocida" (indica que una marca
  no se resolvió y el ID legacy llegó hasta el HTML).
- Un producto en `products.json` no tiene `nombre_normalizado`, `tienda_mas_barata`,
  precios, o `marca`.

**Solución**:
- Si es "desconocida" en HTML: busca en `data/products.json` el producto con `marca: ""`
  o `marca: "Desconocida"` y corrígelo en el scraper.
- Si es campo vacío: el scraper de esa tienda devolvió un campo sin dato. Corre el scraper
  individualmente y depura el extractor del campo en cuestión.

---

### CHECK 7 — €/kg fuera de rango de categoría

**Aparece cuando**: el €/kg de un producto supera 10 veces la mediana de su categoría
(o baja de un 10% de la mediana, check 7b en `build.py`).

**Causas frecuentes**:
- El scraper tomó el precio de un formato diferente (ej. sobres sueltos en vez del bote).
- El peso extraído es incorrecto (ej. 50 g en vez de 500 g → el €/kg es 10× demasiado alto).
- Precio en céntimos en vez de euros.

**Solución**: revisa el precio y el peso del producto en la página real de la tienda.
Depura el scraper y vuelve a correr. Si el precio es correcto (producto genuinamente caro),
ajusta `UMBRAL_KG_ALTO` en `checks.py`.

---

### CHECK 8 — Cambio masivo de IDs

**Aparece cuando**: más del 10% de los IDs del catálogo anterior desaparecen en un build.
Aviso (sin error) entre el 5 y el 10%.

**Causas frecuentes**:
- Se cambió el formato de generación de IDs en el scraper (ej. marca extraída diferente,
  peso en formato distinto).
- Se hizo una limpieza de nombres/marcas que afecta a `id = slug(nombre + marca)`.

**Solución**:
1. Consulta `data/build_stats.json` para ver qué IDs desaparecieron.
2. Si el cambio es intencionado, actualiza `comparaciones.json` y `redirecciones.json`
   con los nuevos IDs.
3. Si no es intencionado, revisa el scraper que genera los IDs.

---

## Archivo de métricas: `data/build_stats.json`

Guardado al final de cada build que pasa todos los checks. Estructura:

```json
{
  "fecha": "2026-09-17",
  "total_productos": 601,
  "por_tienda": {"HSN": 81, "MyProtein": 150, "Nutritienda": 180, "Prozis": 190},
  "n_comparaciones": 57,
  "grupos_multitienda": 6,
  "n_sitemap": 67,
  "ids": ["id1", "id2", "..."]
}
```

Si necesitas comparar manualmente con el estado anterior, `git log data/build_stats.json`
muestra el historial de builds.

---

## Ajustar umbrales

Los umbrales están al principio de `checks.py`:

```python
UMBRAL_TIENDA_DROP = 0.30   # 30% drop por tienda → error
UMBRAL_IDS_WARN    = 0.05   # 5% IDs desaparecidos → aviso
UMBRAL_IDS_ERROR   = 0.10   # 10% IDs desaparecidos → error
UMBRAL_KG_ALTO     = 10.0   # €/kg > 10× mediana → anómalo
```

Si un check salta repetidamente por razones legítimas (ej. un producto genuinamente
caro), ajusta el umbral correspondiente y documenta el motivo en el commit.
