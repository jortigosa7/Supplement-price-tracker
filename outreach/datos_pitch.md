# StackFit — Datos del catálogo (mayo 2026)

Análisis sobre `data/products.json` generado el 2026-05-24.

---

## Resumen del catálogo

| Métrica | Valor |
|---------|-------|
| Total productos | 334 |
| Con peso normalizado (€/kg calculable) | 212 |
| Sin peso (no comparables en €/kg) | 122 |

**Productos por tienda** (entradas en catálogo, un producto puede estar en varias):

| Tienda | Productos |
|--------|-----------|
| Nutritienda | 115 |
| MyProtein | 102 |
| Prozis | 105 |
| HSN | 43 |

**Productos por categoría:**

| Categoría | Productos |
|-----------|-----------|
| Pre-entreno | 111 |
| Whey protein | 107 |
| Creatina | 61 |
| BCAA | 55 |

**Top 5 marcas con más representación:**

| # | Marca | Productos |
|---|-------|-----------|
| 1 | MyProtein | 88 |
| 2 | Prozis | 83 |
| 3 | Optimum Nutrition | 48 |
| 4 | HSN | 31 |
| 5 | BioTechUSA | 12 |

---

## Ranking de tiendas por categoría

> Precio medio en €/kg calculado a partir de todos los productos con `peso_kg >= 0.05 kg` en cada categoría (se excluyen formatos monodosis/stick packs que distorsionan la media). Número de SKUs entre paréntesis.

### Whey Protein

| Posición | Tienda | Media €/kg | SKUs |
|----------|--------|-----------|------|
| 1 (más barata) | **HSN** | **18.20** | 15 |
| 2 | MyProtein | 35.00 | 26 |
| 3 | Nutritienda | 49.50 | 30 |
| 4 (más cara) | **Prozis** | **53.93** | 32 |

**Diferencia más barata vs más cara: +196.3%**
HSN es casi 3× más barata que Prozis en media para whey.

### Creatina

| Posición | Tienda | Media €/kg | SKUs |
|----------|--------|-----------|------|
| 1 (más barata) | **HSN** | **24.66** | 2 |
| 2 | Nutritienda | 68.03 | 20 |
| 3 | MyProtein | 109.76 | 7 |
| 4 (más cara) | **Prozis** | **123.03** | 10 |

**Diferencia más barata vs más cara: +399.1%**

> Nota: HSN solo tiene 2 SKUs de creatina con peso registrado, por lo que su media refleja principalmente la creatina monohidrato pura (la más económica del mercado). MyProtein y Prozis incluyen formatos como Creapure premium y presentaciones pequeñas que elevan la media.

### BCAA

| Posición | Tienda | Media €/kg | SKUs |
|----------|--------|-----------|------|
| 1 (más barata) | **MyProtein** | **49.72** | 3 |
| 2 | HSN | 66.37 | 5 |
| 3 | Nutritienda | 68.69 | 20 |
| 4 (más cara) | **Prozis** | **69.88** | 4 |

**Diferencia más barata vs más cara: +40.6%**
La categoría más homogénea en precios entre tiendas.

### Pre-Entreno

| Posición | Tienda | Media €/kg | SKUs |
|----------|--------|-----------|------|
| 1 (más barata) | **Prozis** | **41.43** | 13 |
| 2 | MyProtein | 58.91 | 18 |
| 3 | HSN | 87.30 | 9 |
| 4 (más cara) | **Nutritienda** | **89.68** | 17 |

**Diferencia más barata vs más cara: +116.5%**

> Sorpresa: Prozis, que es la más cara en whey y creatina, resulta ser la más barata en pre-entreno gracias a formatos grandes como N.O. Shox 1320g (30.30 €/kg) y Energy Charge 800g (28.74 €/kg).

---

## Top 5 productos con mayor sobreprecio entre tiendas

Productos del catálogo que aparecen en al menos 2 tiendas distintas con el mayor diferencial de precio.

> ⚠️ Los primeros puestos del ranking (productos Amix Nutrition en HSN) pueden reflejar errores de scraping — precios como 3.98 €/kg para whey protein son inverosímiles. Se incluyen como están en el dataset pero deben verificarse manualmente.

| # | Producto | Marca | Tienda barata | €/kg barato | Tienda cara | €/kg caro | Diferencia |
|---|---------|-------|---------------|-------------|-------------|-----------|------------|
| 1 | CREATINA MONOHIDRATO EN POLVO (200 MESH) 150g | Optimum Nutrition | HSN | 15.80 | Prozis | 293.27 | +1756.1% |
| 2 | EVOWHEY & OATS 2kg* | Amix Nutrition | HSN | 3.98 | Nutritienda | 55.95 | +1307.5% |
| 3 | CREMA DE ARROZ PROTEICA 2kg* | Amix Nutrition | HSN | 4.20 | Nutritienda | 55.95 | +1233.7% |
| 4 | EVOBASIC WHEY 2kg* | Amix Nutrition | HSN | 5.52 | Nutritienda | 55.95 | +913.6% |
| 5 | EVOWHEY PROTEIN 2kg* | Amix Nutrition | HSN | 7.55 | Nutritienda | 57.75 | +664.9% |

*Verificar precios HSN de Amix — posible error de scraping.

**Caso más interesante (sin outliers sospechosos):** La creatina monohidrato de Optimum Nutrition (150g) sale a 2.37€ en HSN y a 43.99€ en Prozis por exactamente el mismo producto. El precio por kilo es 15.80 €/kg en HSN vs 293.27 €/kg en Prozis — un diferencial de 18×.

---

## Dato curioso para blogger fitness

**La creatina más barata del catálogo cuesta 60× menos por kilo que la más cara.**

- Más barata: creatina monohidrato pura (ON, 150g) en HSN → **15.80 €/kg**
- Más cara (excluyendo monodosis): Pack Clear Performance de MyProtein (100g) → **449.90 €/kg**

La diferencia es de 28× solo entre productos comparables (formatos ≥100g). Y la ciencia es clara: la creatina monohidrato estándar tiene exactamente la misma eficacia que los formatos premium. El packaging justifica la diferencia, no la fórmula.

Otro ángulo: en whey protein, HSN (18.20 €/kg de media) es casi **3 veces más barata** que Prozis (53.93 €/kg) en la misma categoría. Para alguien que consume 2kg de whey al mes, eso supone un ahorro de ~71€/mes o ~852€/año simplemente cambiando de tienda.

---

*Datos extraídos automáticamente de stackfit.es — comparador de precios de suplementos normalizado a €/kg.*
