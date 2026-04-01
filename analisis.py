"""
analisis.py - Análisis Exploratorio del Dataset de Suplementos
===============================================================

Este script genera gráficas y estadísticas del dataset scrapeado.
Es la pieza clave de tu portfolio de data science.

Uso:
    python analisis.py

Qué genera:
    - graficas/01_precio_por_categoria.png
    - graficas/02_top_marcas.png
    - graficas/03_precio_por_kg_distribucion.png
    - graficas/04_precio_vs_peso.png
    - graficas/05_mejores_ofertas.png
    - graficas/resumen_completo.png  (dashboard con todo junto)

Librerías necesarias:
    pip install pandas matplotlib seaborn
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import os
import glob
from datetime import datetime

# ============================================================
# CONFIGURACIÓN VISUAL
# ============================================================

# Estilo profesional para las gráficas
sns.set_theme(style="whitegrid")
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "figure.facecolor": "white",
})

# Paleta de colores profesional
COLORES = ["#2196F3", "#FF9800", "#4CAF50", "#E91E63", "#9C27B0", 
           "#00BCD4", "#FF5722", "#795548", "#607D8B", "#CDDC39"]

# Carpeta de salida
OUTPUT_DIR = "graficas"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# CARGAR DATOS
# ============================================================

def cargar_dataset() -> pd.DataFrame:
    """Busca el CSV más reciente en la carpeta datasets/"""
    
    archivos = glob.glob("datasets/suplementos_*.csv")
    
    if not archivos:
        print("❌ No se encontró ningún dataset en la carpeta datasets/")
        print("   Ejecuta primero: python scraper.py")
        exit(1)
    
    # Coger el más reciente
    archivo = max(archivos, key=os.path.getmtime)
    print(f"📂 Cargando: {archivo}")
    
    df = pd.read_csv(archivo)
    print(f"📊 {len(df)} productos cargados")
    print(f"   Columnas: {', '.join(df.columns)}")
    
    return df


# ============================================================
# GRÁFICA 1: Precio medio por categoría
# ============================================================

def grafica_precio_por_categoria(df: pd.DataFrame):
    """
    Gráfico de barras: precio medio por kg en cada categoría.
    
    POR QUÉ ESTA GRÁFICA ES IMPORTANTE:
    Muestra al comprador qué tipo de suplemento es más caro por kg.
    Es la métrica más útil para comparar.
    """
    print("\n📊 Generando: Precio por categoría...")
    
    # Filtrar productos que tienen precio_por_kg válido
    df_valid = df.dropna(subset=["precio_por_kg"])
    
    if df_valid.empty:
        print("   ⚠️  No hay datos de precio/kg")
        return
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Calcular estadísticas por categoría
    stats = df_valid.groupby("categoria")["precio_por_kg"].agg(["mean", "median", "min", "max", "count"])
    stats = stats.sort_values("mean", ascending=True)
    
    # Gráfico de barras horizontales con media y rango
    barras = ax.barh(
        stats.index, 
        stats["mean"], 
        color=COLORES[:len(stats)],
        edgecolor="white",
        linewidth=0.5,
        height=0.6,
    )
    
    # Añadir el rango min-max como línea
    for i, (cat, row) in enumerate(stats.iterrows()):
        ax.plot([row["min"], row["max"]], [i, i], 
                color="gray", linewidth=1.5, zorder=5)
        ax.plot(row["min"], i, "o", color="green", markersize=5, zorder=6)
        ax.plot(row["max"], i, "o", color="red", markersize=5, zorder=6)
        
        # Etiqueta con el precio medio
        ax.text(row["mean"] + 1, i, f'{row["mean"]:.1f} €/kg', 
                va="center", fontsize=10, fontweight="bold")
    
    ax.set_xlabel("Precio por kg (EUR)")
    ax.set_title("Precio medio por kg según categoría de suplemento\n"
                 "(● verde = más barato | ● rojo = más caro)",
                 fontweight="bold")
    
    # Añadir leyenda con número de productos
    for i, (cat, row) in enumerate(stats.iterrows()):
        ax.text(-2, i, f'n={int(row["count"])}', va="center", 
                fontsize=9, color="gray", ha="right")
    
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "01_precio_por_categoria.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"   ✅ Guardada: {path}")


# ============================================================
# GRÁFICA 2: Top marcas por número de productos
# ============================================================

def grafica_top_marcas(df: pd.DataFrame):
    """
    Gráfico de barras: marcas con más productos en el dataset.
    """
    print("\n📊 Generando: Top marcas...")
    
    # Filtrar marcas vacías
    df_marcas = df[df["marca"].notna() & (df["marca"] != "") & (df["marca"] != "Desconocida")]
    
    if df_marcas.empty:
        print("   ⚠️  No hay datos de marcas")
        return
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # --- Panel izquierdo: Top 10 marcas por cantidad ---
    top_marcas = df_marcas["marca"].value_counts().head(10)
    
    axes[0].barh(top_marcas.index[::-1], top_marcas.values[::-1], 
                 color=COLORES[:len(top_marcas)], edgecolor="white")
    axes[0].set_xlabel("Número de productos")
    axes[0].set_title("Top 10 marcas por cantidad\nde productos", fontweight="bold")
    
    for i, v in enumerate(top_marcas.values[::-1]):
        axes[0].text(v + 0.2, i, str(v), va="center", fontweight="bold")
    
    # --- Panel derecho: Precio medio por kg de las top marcas ---
    df_top = df_marcas[df_marcas["marca"].isin(top_marcas.index)]
    df_top_valid = df_top.dropna(subset=["precio_por_kg"])
    
    if not df_top_valid.empty:
        precio_por_marca = df_top_valid.groupby("marca")["precio_por_kg"].mean().sort_values()
        
        colores_precio = ["#4CAF50" if v <= precio_por_marca.median() else "#FF9800" 
                          for v in precio_por_marca.values]
        
        axes[1].barh(precio_por_marca.index, precio_por_marca.values,
                     color=colores_precio, edgecolor="white")
        axes[1].set_xlabel("Precio medio por kg (EUR)")
        axes[1].set_title("Precio medio por kg\n(verde = por debajo de la mediana)", 
                          fontweight="bold")
        
        for i, (marca, v) in enumerate(precio_por_marca.items()):
            axes[1].text(v + 1, i, f'{v:.1f}€', va="center", fontsize=9)
    
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "02_top_marcas.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"   ✅ Guardada: {path}")


# ============================================================
# GRÁFICA 3: Distribución de precio por kg
# ============================================================

def grafica_distribucion_precio(df: pd.DataFrame):
    """
    Histograma + boxplot: cómo se distribuyen los precios por kg.
    """
    print("\n📊 Generando: Distribución de precios...")
    
    df_valid = df.dropna(subset=["precio_por_kg"])
    
    # Filtrar outliers extremos para la visualización
    q99 = df_valid["precio_por_kg"].quantile(0.99)
    df_plot = df_valid[df_valid["precio_por_kg"] <= q99]
    
    if df_plot.empty:
        print("   ⚠️  No hay datos suficientes")
        return
    
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), 
                              gridspec_kw={"height_ratios": [3, 1]},
                              sharex=True)
    
    # --- Histograma ---
    for cat in df_plot["categoria"].unique():
        datos_cat = df_plot[df_plot["categoria"] == cat]["precio_por_kg"]
        axes[0].hist(datos_cat, bins=15, alpha=0.6, label=f"{cat} (n={len(datos_cat)})",
                     edgecolor="white")
    
    axes[0].set_ylabel("Número de productos")
    axes[0].set_title("Distribución de precios por kg", fontweight="bold")
    axes[0].legend()
    axes[0].axvline(df_plot["precio_por_kg"].median(), color="red", 
                     linestyle="--", label="Mediana", alpha=0.7)
    
    # --- Boxplot por categoría ---
    categorias_presentes = df_plot["categoria"].unique()
    datos_box = [df_plot[df_plot["categoria"] == cat]["precio_por_kg"].values 
                 for cat in categorias_presentes]
    
    bp = axes[1].boxplot(datos_box, vert=False, labels=categorias_presentes,
                          patch_artist=True, widths=0.6)
    
    for patch, color in zip(bp["boxes"], COLORES[:len(categorias_presentes)]):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    
    axes[1].set_xlabel("Precio por kg (EUR)")
    
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "03_precio_por_kg_distribucion.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"   ✅ Guardada: {path}")


# ============================================================
# GRÁFICA 4: Precio vs Peso (scatter plot)
# ============================================================

def grafica_precio_vs_peso(df: pd.DataFrame):
    """
    Scatter plot: relación entre el peso del producto y su precio.
    Muestra si comprar más cantidad sale más barato por kg.
    """
    print("\n📊 Generando: Precio vs Peso...")
    
    df_valid = df.dropna(subset=["precio_eur", "peso_kg", "precio_por_kg"])
    df_valid = df_valid[df_valid["peso_kg"] > 0]
    
    if len(df_valid) < 3:
        print("   ⚠️  No hay datos suficientes")
        return
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    categorias = df_valid["categoria"].unique()
    
    for i, cat in enumerate(categorias):
        datos = df_valid[df_valid["categoria"] == cat]
        scatter = ax.scatter(
            datos["peso_kg"], 
            datos["precio_eur"],
            c=COLORES[i % len(COLORES)],
            s=80,
            alpha=0.7,
            label=f"{cat} ({len(datos)})",
            edgecolors="white",
            linewidth=0.5,
        )
    
    ax.set_xlabel("Peso del producto (kg)")
    ax.set_ylabel("Precio (EUR)")
    ax.set_title("Precio vs Peso del producto por categoría\n"
                 "(los productos más grandes ¿son más baratos por kg?)",
                 fontweight="bold")
    ax.legend(title="Categoría", loc="upper left")
    
    # Añadir líneas de referencia de precio/kg
    if df_valid["peso_kg"].max() > 0:
        x_range = [0.1, df_valid["peso_kg"].max() * 1.1]
        for precio_kg in [20, 40, 80]:
            y_vals = [precio_kg * x for x in x_range]
            if max(y_vals) <= df_valid["precio_eur"].max() * 1.5:
                ax.plot(x_range, y_vals, '--', color='gray', alpha=0.3, linewidth=1)
                ax.text(x_range[1], y_vals[1], f'{precio_kg}€/kg', 
                        color='gray', fontsize=8, alpha=0.6)
    
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "04_precio_vs_peso.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"   ✅ Guardada: {path}")


# ============================================================
# GRÁFICA 5: Top mejores ofertas (mejor precio/kg)
# ============================================================

def grafica_mejores_ofertas(df: pd.DataFrame):
    """
    Tabla visual con los 15 productos con mejor precio por kg.
    """
    print("\n📊 Generando: Mejores ofertas...")
    
    df_valid = df.dropna(subset=["precio_por_kg"])
    df_valid = df_valid[df_valid["precio_por_kg"] > 0]
    
    if df_valid.empty:
        print("   ⚠️  No hay datos")
        return
    
    # Top 15 más baratos por kg
    top = df_valid.nsmallest(15, "precio_por_kg").copy()
    top["label"] = top["nombre"].str[:45]  # Truncar nombres largos
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Asignar color por categoría
    cat_colors = {cat: COLORES[i % len(COLORES)] for i, cat in enumerate(df_valid["categoria"].unique())}
    colores = [cat_colors.get(cat, "gray") for cat in top["categoria"]]
    
    barras = ax.barh(range(len(top)), top["precio_por_kg"].values,
                      color=colores, edgecolor="white", height=0.7)
    
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(top["label"].values, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Precio por kg (EUR)")
    ax.set_title("Top 15 suplementos más baratos por kg", fontweight="bold", fontsize=14)
    
    # Etiquetas con precio y categoría
    for i, (_, row) in enumerate(top.iterrows()):
        ax.text(row["precio_por_kg"] + 0.5, i, 
                f'{row["precio_por_kg"]:.1f} €/kg  |  {row["categoria"]}', 
                va="center", fontsize=9)
    
    # Leyenda de categorías
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=cat_colors[cat], label=cat) 
                       for cat in cat_colors if cat in top["categoria"].values]
    ax.legend(handles=legend_elements, loc="lower right", title="Categoría")
    
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "05_mejores_ofertas.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"   ✅ Guardada: {path}")


# ============================================================
# ESTADÍSTICAS DE TEXTO
# ============================================================

def imprimir_estadisticas(df: pd.DataFrame):
    """Imprime un resumen estadístico completo."""
    
    print("\n" + "=" * 60)
    print("📈 ANÁLISIS ESTADÍSTICO COMPLETO")
    print("=" * 60)
    
    print(f"\n--- DATASET ---")
    print(f"   Productos totales: {len(df)}")
    print(f"   Categorías: {df['categoria'].nunique()}")
    print(f"   Marcas únicas: {df['marca'].nunique()}")
    print(f"   Fecha de scraping: {df['fecha_scraping'].iloc[0] if 'fecha_scraping' in df.columns else 'N/A'}")
    
    df_valid = df.dropna(subset=["precio_eur"])
    
    print(f"\n--- PRECIOS ---")
    print(f"   Media:    {df_valid['precio_eur'].mean():.2f} EUR")
    print(f"   Mediana:  {df_valid['precio_eur'].median():.2f} EUR")
    print(f"   Mínimo:   {df_valid['precio_eur'].min():.2f} EUR")
    print(f"   Máximo:   {df_valid['precio_eur'].max():.2f} EUR")
    print(f"   Desv. estándar: {df_valid['precio_eur'].std():.2f} EUR")
    
    df_pkg = df.dropna(subset=["precio_por_kg"])
    if not df_pkg.empty:
        print(f"\n--- PRECIO POR KG ---")
        for cat in sorted(df_pkg["categoria"].unique()):
            datos = df_pkg[df_pkg["categoria"] == cat]["precio_por_kg"]
            print(f"\n   {cat}:")
            print(f"     Media:   {datos.mean():.2f} EUR/kg")
            print(f"     Mediana: {datos.median():.2f} EUR/kg")
            print(f"     Rango:   {datos.min():.2f} - {datos.max():.2f} EUR/kg")
            print(f"     Productos con precio/kg: {len(datos)}")
        
        print(f"\n--- 🏆 MEJORES OFERTAS POR CATEGORÍA ---")
        for cat in sorted(df_pkg["categoria"].unique()):
            mejor = df_pkg[df_pkg["categoria"] == cat].nsmallest(1, "precio_por_kg").iloc[0]
            print(f"   {cat}: {mejor['nombre']}")
            print(f"     → {mejor['precio_por_kg']:.2f} EUR/kg ({mejor['precio_eur']:.2f}€)")
    
    # Marcas con mejor relación calidad/precio
    df_marcas = df_pkg[df_pkg["marca"].notna() & (df_pkg["marca"] != "")]
    if not df_marcas.empty:
        print(f"\n--- MARCAS MÁS ECONÓMICAS (media de precio/kg) ---")
        marcas_media = df_marcas.groupby("marca").agg(
            precio_kg_medio=("precio_por_kg", "mean"),
            productos=("nombre", "count")
        ).sort_values("precio_kg_medio")
        
        # Solo marcas con al menos 2 productos
        marcas_relevantes = marcas_media[marcas_media["productos"] >= 2].head(5)
        for marca, row in marcas_relevantes.iterrows():
            print(f"   {marca}: {row['precio_kg_medio']:.2f} EUR/kg ({int(row['productos'])} productos)")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║   📊 ANÁLISIS EXPLORATORIO - SUPLEMENTOS FITNESS        ║
    ║   Portfolio de Data Science                              ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # Cargar datos
    df = cargar_dataset()
    
    # Estadísticas de texto
    imprimir_estadisticas(df)
    
    # Generar gráficas
    print("\n" + "=" * 60)
    print("🎨 GENERANDO GRÁFICAS")
    print("=" * 60)
    
    grafica_precio_por_categoria(df)
    grafica_top_marcas(df)
    grafica_distribucion_precio(df)
    grafica_precio_vs_peso(df)
    grafica_mejores_ofertas(df)
    
    print(f"\n{'='*60}")
    print(f"✅ ANÁLISIS COMPLETADO")
    print(f"{'='*60}")
    print(f"\n   Todas las gráficas guardadas en: {OUTPUT_DIR}/")
    print(f"   Ábrelas con el explorador de archivos o desde VS Code.")
    
    print("""
    💡 PARA TU PORTFOLIO:
    
    Sube estas gráficas junto con el código a GitHub o Kaggle.
    Un buen README del proyecto incluiría:
    
    1. Descripción del pipeline (scraping → limpieza → análisis)
    2. Las gráficas generadas con interpretación
    3. Conclusiones (ej: "HSN ofrece el mejor precio/kg en proteínas")
    4. Stack técnico: Python, BeautifulSoup, Pandas, Matplotlib
    """)
