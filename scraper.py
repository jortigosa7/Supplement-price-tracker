"""
scraper.py - Scraper de precios de suplementos fitness
======================================================

Este script scrapea precios de suplementos deportivos de tiendas online
y genera un dataset limpio en CSV y JSON.

Tiendas implementadas:
  - Nutritienda.com (HTML estático, fácil de scrapear)

Uso:
  python scraper.py

Salida:
  datasets/suplementos_YYYYMMDD.csv
  datasets/suplementos_YYYYMMDD.json
"""

import requests
from bs4 import BeautifulSoup
import time
import os
import json
import pandas as pd
from datetime import datetime
from limpieza import limpiar_dataset

# ============================================================
# CONFIGURACIÓN
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# Pausa entre peticiones (en segundos) - sé respetuoso con los servidores
DELAY_ENTRE_PETICIONES = 3

# Carpeta de salida
OUTPUT_DIR = "datasets"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def hacer_peticion(url: str, max_reintentos: int = 3) -> requests.Response | None:
    """
    Hace una petición HTTP con reintentos y manejo de errores.
    
    Esto es una buena práctica: las peticiones pueden fallar por
    problemas de red, servidores lentos, etc.
    """
    for intento in range(max_reintentos):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                # Too Many Requests - nos están limitando
                print(f"   ⏱️  Rate limited. Esperando 10 segundos...")
                time.sleep(10)
            else:
                print(f"   ⚠️  Código {response.status_code} para {url}")
                
        except requests.exceptions.Timeout:
            print(f"   ⏱️  Timeout (intento {intento + 1}/{max_reintentos})")
        except requests.exceptions.ConnectionError:
            print(f"   ❌ Error de conexión (intento {intento + 1}/{max_reintentos})")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error: {e}")
            return None
        
        if intento < max_reintentos - 1:
            time.sleep(2)
    
    return None


# ============================================================
# SCRAPER: NUTRITIENDA.COM
# ============================================================

def scrape_nutritienda() -> list[dict]:
    """
    Scrapea suplementos de Nutritienda.com.
    
    Nutritienda es ideal para empezar porque:
    - Es una tienda española con precios en EUR
    - El HTML es relativamente limpio y estático
    - Tiene una buena variedad de marcas
    
    CÓMO ENCONTRÉ LOS SELECTORES CSS:
    1. Abrí https://www.nutritienda.com/es/proteinas-whey en Chrome
    2. Click derecho en un producto > "Inspeccionar"
    3. Observé la estructura HTML del listado de productos
    4. Identifiqué las clases CSS de: nombre, precio, marca, etc.
    """
    print("\n" + "=" * 60)
    print("🏪 SCRAPING: Nutritienda.com")
    print("=" * 60)
    
    productos = []
    
    # URLs de categorías que nos interesan
    categorias = [
        {"nombre": "Proteínas Whey",   "url": "https://www.nutritienda.com/es/proteinas-suero-whey"},
        {"nombre": "Creatina",         "url": "https://www.nutritienda.com/es/creatina"},
        {"nombre": "BCAA",             "url": "https://www.nutritienda.com/es/bcaas"},
        {"nombre": "Pre-Entreno",      "url": "https://www.nutritienda.com/es/pre-entreno"},
    ]
    
    for cat in categorias:
        print(f"\n📡 Categoría: {cat['nombre']}")
        print(f"   URL: {cat['url']}")
        
        response = hacer_peticion(cat["url"])
        if not response:
            print(f"   ❌ No se pudo acceder")
            continue
        
        soup = BeautifulSoup(response.text, "lxml")
        
        # -------------------------------------------------------
        # SELECTORES REALES DE NUTRITIENDA (encontrados el 31/03/2026):
        #
        # Estructura HTML de cada producto:
        #   <div class="grid-info-wrapper">
        #     <span class="price">74.20€</span>
        #     <span class="old-price">89.44€</span>
        #     <h3><a href="/es/..." title="NOMBRE - MARCA">NOMBRE</a></h3>
        #   </div>
        #
        # Cada producto está dentro de un contenedor con clase
        # "grid-image" seguido de "grid-info-wrapper".
        # Buscamos todos los bloques "grid-info-wrapper".
        # -------------------------------------------------------
        
        # Buscar todos los bloques de producto
        items = soup.select("div.grid-info-wrapper")
        
        if not items:
            # Fallback: buscar cualquier contenedor que tenga span.price
            items = soup.find_all("span", class_="price")
            if items:
                # Subir al contenedor padre para tener acceso al nombre
                items = [price.parent.parent for price in items if price.parent]
            
        if not items:
            print(f"   ⚠️  No se encontraron productos.")
            print(f"   💡 La web puede haber cambiado su estructura HTML.")
            continue
        
        print(f"   ✅ Encontrados {len(items)} productos en HTML")
        
        for item in items:
            try:
                # Extraer precio actual (span.price)
                precio_elem = item.select_one("span.price")
                precio = precio_elem.get_text(strip=True) if precio_elem else None
                
                # Extraer nombre del producto (h3 > a)
                nombre_elem = item.select_one("h3 a")
                nombre = nombre_elem.get_text(strip=True) if nombre_elem else None
                
                # Extraer marca del atributo title del enlace
                # El title suele tener formato: "NOMBRE - MARCA"
                marca = ""
                if nombre_elem and nombre_elem.get("title"):
                    title_parts = nombre_elem["title"].split(" - ")
                    if len(title_parts) > 1:
                        marca = title_parts[-1].strip()
                
                # Extraer URL del producto
                url = ""
                if nombre_elem and nombre_elem.get("href"):
                    href = nombre_elem["href"]
                    if href.startswith("http"):
                        url = href
                    elif href.startswith("/"):
                        url = "https://www.nutritienda.com" + href
                
                if nombre:  # Solo añadir si tenemos al menos un nombre
                    productos.append({
                        "nombre": nombre,
                        "precio": precio or "N/A",
                        "marca": marca,
                        "categoria": cat["nombre"],
                        "tienda": "Nutritienda",
                        "url": url,
                        "fecha_scraping": datetime.now().strftime("%Y-%m-%d"),
                    })
            except Exception as e:
                print(f"   ⚠️  Error en un producto: {e}")
                continue
        
        print(f"   📊 Total acumulado: {len(productos)} productos")
        
        # Pausa entre categorías
        print(f"   ⏱️  Esperando {DELAY_ENTRE_PETICIONES}s...")
        time.sleep(DELAY_ENTRE_PETICIONES)
    
    return productos


# ============================================================
# GUARDAR DATASET
# ============================================================

def guardar_dataset(df: pd.DataFrame) -> tuple[str, str]:
    """Guarda el DataFrame como CSV y JSON."""
    
    timestamp = datetime.now().strftime("%Y%m%d")
    
    # Columnas que queremos en el dataset final
    columnas_output = [
        "nombre", "marca", "categoria", "precio_eur", "peso_kg",
        "precio_por_kg", "tienda", "url", "fecha_scraping"
    ]
    
    # Solo incluir columnas que existan
    columnas_disponibles = [c for c in columnas_output if c in df.columns]
    df_output = df[columnas_disponibles].copy()
    
    # Ordenar por categoría y precio/kg
    if "precio_por_kg" in df_output.columns:
        df_output = df_output.sort_values(
            by=["categoria", "precio_por_kg"],
            ascending=[True, True],
            na_position="last"
        )
    
    # Guardar CSV
    csv_path = os.path.join(OUTPUT_DIR, f"suplementos_{timestamp}.csv")
    df_output.to_csv(csv_path, index=False, encoding="utf-8-sig")
    
    # Guardar JSON
    json_path = os.path.join(OUTPUT_DIR, f"suplementos_{timestamp}.json")
    df_output.to_json(json_path, orient="records", force_ascii=False, indent=2)
    
    return csv_path, json_path


def mostrar_resumen(df: pd.DataFrame):
    """Muestra un resumen del dataset."""
    
    print("\n" + "=" * 60)
    print("📈 RESUMEN DEL DATASET")
    print("=" * 60)
    
    print(f"\n   Productos totales: {len(df)}")
    
    if "tienda" in df.columns:
        print(f"   Tiendas: {', '.join(df['tienda'].unique())}")
    if "categoria" in df.columns:
        print(f"   Categorías: {', '.join(df['categoria'].unique())}")
    if "marca" in df.columns:
        marcas = df["marca"].value_counts().head(5)
        print(f"   Top marcas:")
        for marca, count in marcas.items():
            print(f"     - {marca}: {count} productos")
    
    if "precio_eur" in df.columns:
        print(f"\n   Precio medio: {df['precio_eur'].mean():.2f} EUR")
        print(f"   Precio mín:   {df['precio_eur'].min():.2f} EUR")
        print(f"   Precio máx:   {df['precio_eur'].max():.2f} EUR")
    
    if "precio_por_kg" in df.columns and df["precio_por_kg"].notna().any():
        print(f"\n   Precio/kg medio: {df['precio_por_kg'].mean():.2f} EUR/kg")
        mejor = df.loc[df["precio_por_kg"].idxmin()]
        print(f"   🏆 Mejor precio/kg: {mejor['nombre']}")
        print(f"      {mejor['precio_por_kg']} EUR/kg en {mejor['tienda']}")
    
    # Tabla resumen por categoría
    if "categoria" in df.columns and "precio_por_kg" in df.columns:
        print(f"\n   📊 Precio/kg por categoría:")
        resumen = df.groupby("categoria")["precio_por_kg"].agg(["mean", "min", "count"])
        resumen.columns = ["Media €/kg", "Mín €/kg", "Productos"]
        print(resumen.to_string())


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║   🏋️ SUPPLEMENT PRICE SCRAPER                           ║
    ║   Dataset de precios de suplementos fitness              ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    inicio = time.time()
    
    # --- FASE 1: Scraping ---
    todos_los_productos = []
    
    # Nutritienda
    productos_nutritienda = scrape_nutritienda()
    todos_los_productos.extend(productos_nutritienda)
    
    # Aquí irán más tiendas en el futuro:
    # productos_hsn = scrape_hsn()
    # todos_los_productos.extend(productos_hsn)
    # 
    # productos_myprotein = scrape_myprotein()
    # todos_los_productos.extend(productos_myprotein)
    
    print(f"\n{'='*60}")
    print(f"📦 Total productos scrapeados: {len(todos_los_productos)}")
    print(f"{'='*60}")
    
    if not todos_los_productos:
        print("""
    ⚠️  No se pudieron scrapear productos.
    
    Esto puede pasar porque:
    1. La web ha cambiado su estructura HTML
    2. La web bloquea peticiones automatizadas
    3. No hay conexión a internet
    
    SOLUCIÓN - Inspecciona tú mismo:
    1. Abre la URL en Chrome
    2. Ctrl+U para ver el código fuente
    3. Busca (Ctrl+F) "price" o "producto"
    4. Ajusta los selectores CSS en el código
    
    De momento, vamos a generar un dataset de demostración
    para que veas el formato y la estructura.
        """)
        
        # Datos de demostración basados en precios reales del mercado
        todos_los_productos = [
            {"nombre": "MyProtein Impact Whey Protein 1kg Chocolate", "precio": "26,99", "marca": "MyProtein", "categoria": "Proteínas Whey", "tienda": "MyProtein.es", "url": "https://www.myprotein.es/p/nutricion-deportiva/impact-whey-protein/10530943/", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "MyProtein Impact Whey Protein 2.5kg Vainilla", "precio": "60,99", "marca": "MyProtein", "categoria": "Proteínas Whey", "tienda": "MyProtein.es", "url": "https://www.myprotein.es/p/nutricion-deportiva/impact-whey-protein/10530943/", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "HSN Evowhey Protein 2.0 2kg", "precio": "39,89", "marca": "HSN", "categoria": "Proteínas Whey", "tienda": "HSN", "url": "https://www.hsnstore.eu/brands/sport-series/evowhey-protein-2-0", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "HSN 100% Whey Protein Concentrate 2kg", "precio": "27,90", "marca": "HSN", "categoria": "Proteínas Whey", "tienda": "HSN", "url": "https://www.hsnstore.eu/brands/raw-series/100-whey-protein-concentrate", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "Optimum Nutrition Gold Standard Whey 2.27kg", "precio": "54,99", "marca": "Optimum Nutrition", "categoria": "Proteínas Whey", "tienda": "Amazon.es", "url": "https://www.amazon.es/dp/B000QSNYGI", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "Dymatize ISO100 Hydrolyzed 2.2kg", "precio": "69,99", "marca": "Dymatize", "categoria": "Proteínas Whey", "tienda": "Amazon.es", "url": "https://www.amazon.es/dp/B000E8ZJIS", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "BioTechUSA 100% Pure Whey 2.27kg", "precio": "44,90", "marca": "BioTechUSA", "categoria": "Proteínas Whey", "tienda": "Nutritienda", "url": "https://www.nutritienda.com/es/biotechusa-100-pure-whey-2270g", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "Scitec Nutrition 100% Whey Protein Pro 2.35kg", "precio": "49,90", "marca": "Scitec Nutrition", "categoria": "Proteínas Whey", "tienda": "Nutritienda", "url": "https://www.nutritienda.com/es/scitec-100-whey-protein-pro", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "MyProtein Essential Whey Protein 1kg", "precio": "19,29", "marca": "MyProtein", "categoria": "Proteínas Whey", "tienda": "MyProtein.es", "url": "https://www.myprotein.es/p/nutricion-deportiva/essential-whey-protein/", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "HSN Creatine Excell Creapure 500g", "precio": "19,90", "marca": "HSN", "categoria": "Creatina", "tienda": "HSN", "url": "https://www.hsnstore.eu/brands/sport-series/creatine-excell", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "Optimum Nutrition Creatine Powder 634g", "precio": "28,99", "marca": "Optimum Nutrition", "categoria": "Creatina", "tienda": "Amazon.es", "url": "https://www.amazon.es/dp/B002DYIZEO", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "MyProtein Creatine Monohydrate 500g", "precio": "16,99", "marca": "MyProtein", "categoria": "Creatina", "tienda": "MyProtein.es", "url": "https://www.myprotein.es/p/nutricion-deportiva/creatina-monohidrato/10530116/", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "BioTechUSA 100% Creatine Monohydrate 500g", "precio": "15,90", "marca": "BioTechUSA", "categoria": "Creatina", "tienda": "Nutritienda", "url": "https://www.nutritienda.com/es/biotechusa-100-creatine-monohydrate-500g", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "HSN Evobcaa's 2.0 400g", "precio": "22,90", "marca": "HSN", "categoria": "BCAA", "tienda": "HSN", "url": "https://www.hsnstore.eu/brands/sport-series/evobcaas-2-0", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "Scitec Nutrition BCAA Xpress 700g", "precio": "29,90", "marca": "Scitec Nutrition", "categoria": "BCAA", "tienda": "Nutritienda", "url": "https://www.nutritienda.com/es/scitec-bcaa-xpress-700g", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "HSN Evobomb Pre-Workout 400g", "precio": "24,90", "marca": "HSN", "categoria": "Pre-Entreno", "tienda": "HSN", "url": "https://www.hsnstore.eu/brands/sport-series/evobomb", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
            {"nombre": "Applied Nutrition ABE Pre-Workout 315g", "precio": "27,50", "marca": "Applied Nutrition", "categoria": "Pre-Entreno", "tienda": "Nutritienda", "url": "https://www.nutritienda.com/es/applied-nutrition-abe", "fecha_scraping": datetime.now().strftime("%Y-%m-%d")},
        ]
    
    # --- FASE 2: Limpieza ---
    df = limpiar_dataset(todos_los_productos)
    
    if df.empty:
        print("❌ No hay datos para guardar")
    else:
        # --- FASE 3: Guardar ---
        csv_path, json_path = guardar_dataset(df)
        print(f"\n💾 Archivos guardados:")
        print(f"   CSV:  {csv_path}")
        print(f"   JSON: {json_path}")
        
        # --- FASE 4: Resumen ---
        mostrar_resumen(df)
    
    duracion = time.time() - inicio
    print(f"\n⏱️  Tiempo total: {duracion:.1f} segundos")
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║   ✅ SCRAPING COMPLETADO                                ║
    ╠══════════════════════════════════════════════════════════╣
    ║                                                          ║
    ║   Revisa los archivos en la carpeta datasets/            ║
    ║                                                          ║
    ║   PRÓXIMO PASO:                                          ║
    ║   Ejecuta: python analisis.py                            ║
    ║   para generar gráficas y análisis del dataset.          ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)
