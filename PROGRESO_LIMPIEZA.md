# Progreso limpieza SEO — rama limpieza-seo
Fecha última sesión: 2026-09-11

## Estado global
- [x] Tarea 1: Bug precio/kg → COMPLETADO (código + datos regenerados)
- [x] Tarea 2: Bug MARCAS_NORM → COMPLETADO
- [x] Tarea 3: Pares comparaciones.json → COMPLETADO (59 pares válidos)
- [x] Tarea 4: Sitemap y recuento de páginas → COMPLETADO
- [x] Tarea 5: 0 enlaces rotos → COMPLETADO
- [x] Tarea 6: Redirects correctas → COMPLETADO
- [x] Tarea 7: Checks varios → COMPLETADO
- [x] Tarea 8: Build idempotente → COMPLETADO

## Sesión 2 (2026-09-11) — fixes adicionales

### Fix precios HSN (datos regenerados)

La sesión anterior corrigió el CÓDIGO pero no regeneró los datos.
products.json seguía con precio_eur: 11.07 para Evobasic (precio de lista 500g).

Solución:
1. Corrió scrapers/hsn.py corregido (63 productos, 100% desde caché)
2. Fusionó con datos no-HSN del dataset anterior (20260907)
3. Deduplicó 4 entradas repetidas resultantes
4. Nuevo raw dataset: datasets/suplementos_20260911_hsn_fix.json (388 productos)
5. build.py regeneró data/products.json y HTML

**Tabla final de precios HSN en comparaciones.json:**
| Producto | Precio | Peso | €/kg |
|---|---|---|---|
| Evobasic whey 2kg | 43.07€ | 2.0kg | 21.54 |
| Evowhey protein 2kg | 54.99€ | 2.0kg | 27.50 |
| Evowhey protein sin edulcorantes 2kg | 56.99€ | 2.0kg | 28.50 |
| Evowhey & oats 2kg | 38.98€ | 2.0kg | 19.49 |
| Evolate 2.0 sin edulcorantes 2kg | 81.99€ | 2.0kg | 41.00 |
| Evohydro 2.0 2kg | 84.49€ | 2.0kg | 42.24 |
| Evolate 2.0 2kg | 93.91€ | 2.0kg | 46.95 |
| 100% Whey protein concentrate | 19.92€ | N/A | N/A (sin precio confirmado por opción) |

### Fix canonical href en redirects

build.py usaba ruta relativa en el canonical de páginas meta-refresh.
Fix: `SITE_URL + hasta_url` para canonical (absoluta), meta refresh sigue relativa.

Ejemplo redirect page HTML:
```html
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=/comparar/evobasic-whey-2kg-hsn-vs-evowhey-protein-2kg-hsn/">
<link rel="canonical" href="https://stackfit.es/comparar/evobasic-whey-2kg-hsn-vs-evowhey-protein-2kg-hsn/">
<title>Redirigiendo...</title>
</head><body>
<p>Esta página ha sido movida. <a href="/comparar/evobasic-whey-2kg-hsn-vs-evowhey-protein-2kg-hsn/">Haz clic aquí si no eres redirigido automáticamente.</a></p>
</body></html>
```

### Fix comparaciones.json (ID cambiado)

El producto `100-whey-protein-concentrate-2kg-desconocida` perdió el `2kg` del nombre
al re-scraper (no se encontró precio en optionPrices JSON para esa opción).
ID nuevo: `100-whey-protein-concentrate-desconocida`

Acciones:
- Actualizada comparaciones.json: 5 pares cambiados al nuevo ID
- Añadidos 10 redirects en redirecciones.json (both directions, con/sin 2kg)
- Actualizados 10 redirects existentes que apuntaban al slug con 2kg

## Checks finales (segunda sesión)

| Check | Estado |
|---|---|
| Build x2 idempotente | ✅ 68 páginas ambas ejecuciones |
| Sitemap | ✅ 69 URLs, 0 redirects, 0 "desconocida" |
| 0 enlaces HTML rotos | ✅ 59+10+116+10 = 185 páginas revisadas |
| 0 cadenas de redirección | ✅ 0 |
| 0 destinos con desconocida | ✅ 0 |
| 0 redirects rotos | ✅ 0 |
| canonical absoluta | ✅ https://stackfit.es/... |
| meta-refresh relativa | ✅ /comparar/... |

## Sesión 3 (2026-09-11) — producción estable

### Fix precios desde caché

Precio y peso ahora siempre vienen de petición fresca a HSN.
`_obtener_precio_peso_fresco(url)` hace 1 petición por producto (sin leer caché),
guarda el HTML en caché, y `_scrape_detalle()` usa esa caché fresca.
~70 peticiones por ejecución (7 listados + 63 detalles frescos).

### Fix estabilidad de IDs

Fallback por URL en `scraper.py`: si HSN devuelve un producto sin peso en el nombre
(select vacío, timeout, etc.), se restaura el nombre anterior (con peso) del último
dataset, preservando el ID de producto.

Bug adicional encontrado y corregido: `build.py` no propagaba `_precio_sin_confirmar`
al construir `productos_para_matching` → el flag se perdía → `matching.py` calculaba
€/kg incorrecto para `100% Whey protein concentrate 2kg`. Corregido añadiendo el campo
al dict en `build.py::cargar_productos()`.

### Fix fallo duro en build.py

`cargar_comparaciones()` ahora llama `sys.exit(1)` con mensaje descriptivo si algún
ID de `comparaciones.json` no existe en `products.json`. GitHub Actions enviará email
cuando el scraper rompa un ID de producto.

### Restauración de comparaciones.json y redirecciones.json

Las 5 referencias y 10 redirects que se cambiaron por el ID temporal
`100-whey-protein-concentrate-desconocida` se han revertido al ID correcto
`100-whey-protein-concentrate-2kg-desconocida`. Las 10 entradas de redirect espurias
(añadidas en sesión 2) se han eliminado. Total: 116 redirects (igual que antes).

### Checks finales (tercera sesión)

| Check | Estado |
|---|---|
| Build x2 idempotente | ✅ 59 comparaciones + 116 redirects ambas ejecuciones |
| Sitemap | ✅ 69 URLs, 0 redirects, 0 "desconocida" |
| 0 enlaces HTML rotos | ✅ 185 páginas revisadas |
| 0 cadenas de redirección | ✅ 0 |
| 0 destinos con desconocida | ✅ 0 |
| 0 redirects rotos | ✅ 0 |
| canonical absoluta | ✅ https://stackfit.es/... |
| meta-refresh relativa | ✅ /comparar/... |
| 100% Whey protein concentrate €/kg | ✅ N/A (sin confirmar, correcto) |

### Tabla de precios HSN (sesión 3, dataset 2026-09-11)

| Producto | Peso | Precio | €/kg |
|---|---|---|---|
| 100% Proteína de suero hidrolizado aislada 2kg | 2.0kg | 68.83€ | 34.41 |
| 100% Whey protein concentrate 2kg | 2.0kg | 19.92€ | N/A (sin confirmar) |
| 100% Whey protein isolate 2kg | 2.0kg | 86.94€ | 43.47 |
| BCAA's instantáneo 2:1:1 2.0 150g | 0.15kg | 4.5€ | 30.0 |
| BCAA's instantáneo 4:1:1 2.0 150g | 0.15kg | 5.64€ | 37.6 |
| Creatina Excell 1000mg (100% Creapure) | N/A | 17.04€ | N/A (sin confirmar) |
| Creatina monohidrato en polvo (200 mesh) 150g | 0.15kg | 2.37€ | 15.8 |
| Evobasic whey 2kg | 2.0kg | 43.07€ | 21.54 |
| Evobeast 1kg | 1.0kg | 28.45€ | 28.45 |
| Evocreatine 500g | 0.5kg | 16.48€ | 32.96 |
| Evoexcel (whey protein isolate + concentrate) 2kg | 2.0kg | 76.99€ | 38.49 |
| Evoexcel sin edulcorantes 2kg | 2.0kg | 78.5€ | 39.25 |
| Evohydro 2.0 (hydro whey) 2kg | 2.0kg | 84.49€ | 42.24 |
| Evolate 2.0 (whey isolate CFM) 2kg | 2.0kg | 93.91€ | 46.95 |
| Evolate 2.0 sin edulcorantes (whey isolate CFM) 2kg | 2.0kg | 81.99€ | 40.99 |
| Evowhey & oats 2kg | 2.0kg | 38.98€ | 19.49 |
| Evowhey protein 2kg | 2.0kg | 54.99€ | 27.5 |
| Evowhey protein sin edulcorantes 2kg | 2.0kg | 56.99€ | 28.5 |
| Golden protein 2kg | 2.0kg | 53.0€ | 26.5 |
| Keto whey protein 2kg | 2.0kg | 64.99€ | 32.49 |
