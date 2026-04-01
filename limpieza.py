"""
limpieza.py - Funciones para limpiar y estructurar los datos scrapeados.

Estas funciones convierten datos "sucios" (texto con símbolos, formatos
inconsistentes) en datos limpios y listos para análisis.
"""

import re
import pandas as pd


def limpiar_precio(precio_str: str) -> float | None:
    """
    Convierte cualquier formato de precio a un número float.
    
    Ejemplos:
        "54,99 €"   -> 54.99
        "€54.99"    -> 54.99
        "54.99€"    -> 54.99
        "1.054,99"  -> 1054.99  (formato europeo con miles)
        "N/A"       -> None
    """
    if pd.isna(precio_str) or not precio_str or str(precio_str).strip() in ("N/A", "-", ""):
        return None
    
    texto = str(precio_str).strip()
    
    # Quitar todo excepto números, puntos y comas
    limpio = re.sub(r'[^\d.,]', '', texto)
    
    if not limpio:
        return None
    
    # Detectar formato europeo: "1.054,99" (punto = miles, coma = decimal)
    if ',' in limpio and '.' in limpio:
        # Si la coma viene después del punto -> formato europeo
        if limpio.rfind(',') > limpio.rfind('.'):
            limpio = limpio.replace('.', '').replace(',', '.')
        else:
            # Formato americano: "1,054.99"
            limpio = limpio.replace(',', '')
    elif ',' in limpio:
        # Solo coma -> probablemente decimal europeo: "54,99"
        limpio = limpio.replace(',', '.')
    
    try:
        return round(float(limpio), 2)
    except ValueError:
        return None


def extraer_peso_kg(nombre: str) -> float | None:
    """
    Extrae el peso del producto del nombre y lo convierte a kg.
    
    Ejemplos:
        "Evowhey Protein 2kg"           -> 2.0
        "Impact Whey 2.5kg"             -> 2.5
        "Creatina Creapure 500g"        -> 0.5
        "Gold Standard Whey 2.27kg"     -> 2.27
        "Impact Whey Protein (1000g)"   -> 1.0
    """
    if pd.isna(nombre) or not nombre:
        return None
    
    texto = str(nombre).lower()
    
    # Buscar kg primero (más específico)
    # Patrones: "2kg", "2.5kg", "2,27kg", "2.5 kg"
    kg_match = re.search(r'(\d+[.,]?\d*)\s*kg', texto)
    if kg_match:
        valor = kg_match.group(1).replace(',', '.')
        return round(float(valor), 3)
    
    # Buscar gramos
    # Patrones: "500g", "1000g", "500 g", "500gr"
    g_match = re.search(r'(\d+)\s*g(?:r)?(?:\b|$)', texto)
    if g_match:
        return round(float(g_match.group(1)) / 1000, 3)
    
    return None


def extraer_marca(nombre: str, marcas_conocidas: list[str] = None) -> str:
    """
    Intenta extraer la marca del nombre del producto.
    Usa una lista de marcas conocidas para buscar coincidencias.
    """
    if marcas_conocidas is None:
        marcas_conocidas = [
            "Optimum Nutrition", "ON", "MyProtein", "Myprotein",
            "HSN", "BioTechUSA", "BioTech USA", "Dymatize",
            "BSN", "MuscleTech", "Scitec", "Scitec Nutrition",
            "Weider", "Amix", "Bulk", "Prozis", "Now Foods",
            "Applied Nutrition", "PhD", "Mutant", "USN",
            "Gold Nutrition", "Quamtrax", "Victory", "Foodspring",
        ]
    
    nombre_lower = str(nombre).lower()
    
    for marca in marcas_conocidas:
        if marca.lower() in nombre_lower:
            return marca
    
    return "Desconocida"


def limpiar_dataset(productos: list[dict]) -> pd.DataFrame:
    """
    Toma la lista de productos scrapeados y devuelve un DataFrame limpio.
    
    Pasos:
    1. Crear DataFrame
    2. Limpiar precios
    3. Extraer pesos
    4. Calcular precio/kg
    5. Limpiar textos
    6. Eliminar duplicados
    """
    if not productos:
        print("⚠️  No hay productos para limpiar")
        return pd.DataFrame()
    
    df = pd.DataFrame(productos)
    print(f"\n🧹 Limpiando {len(df)} productos...")
    
    # 1. Limpiar precios
    df["precio_eur"] = df["precio"].apply(limpiar_precio)
    
    # 2. Extraer peso en kg
    df["peso_kg"] = df["nombre"].apply(extraer_peso_kg)
    
    # 3. Calcular precio por kg (métrica clave para comparar)
    df["precio_por_kg"] = df.apply(
        lambda row: round(row["precio_eur"] / row["peso_kg"], 2)
        if pd.notna(row["precio_eur"]) and pd.notna(row["peso_kg"]) and row["peso_kg"] > 0
        else None,
        axis=1
    )
    
    # 4. Limpiar textos
    for col in ["nombre", "categoria", "tienda"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    
    # 5. Extraer marca si no viene
    if "marca" not in df.columns or df["marca"].isna().all():
        df["marca"] = df["nombre"].apply(extraer_marca)
    
    # 6. Eliminar filas sin precio
    antes = len(df)
    df = df.dropna(subset=["precio_eur"])
    despues = len(df)
    if antes != despues:
        print(f"   Eliminados {antes - despues} productos sin precio válido")
    
    # 7. Eliminar duplicados por nombre + tienda
    antes = len(df)
    df = df.drop_duplicates(subset=["nombre", "tienda"], keep="first")
    despues = len(df)
    if antes != despues:
        print(f"   Eliminados {antes - despues} duplicados")
    
    print(f"✅ Dataset limpio: {len(df)} productos")
    
    return df


# ---- Tests rápidos ----
if __name__ == "__main__":
    print("🧪 Tests de limpieza:\n")
    
    # Test limpiar_precio
    tests_precio = [
        ("54,99 €", 54.99),
        ("€54.99", 54.99),
        ("1.054,99€", 1054.99),
        ("29.42", 29.42),
        ("N/A", None),
        ("", None),
    ]
    for entrada, esperado in tests_precio:
        resultado = limpiar_precio(entrada)
        ok = "✅" if resultado == esperado else "❌"
        print(f"  {ok} limpiar_precio('{entrada}') = {resultado} (esperado: {esperado})")
    
    print()
    
    # Test extraer_peso_kg
    tests_peso = [
        ("Evowhey Protein 2kg", 2.0),
        ("Impact Whey 2.5kg", 2.5),
        ("Creatina 500g", 0.5),
        ("Gold Standard 2.27kg", 2.27),
        ("Whey Protein (1000g)", 1.0),
    ]
    for entrada, esperado in tests_peso:
        resultado = extraer_peso_kg(entrada)
        ok = "✅" if resultado == esperado else "❌"
        print(f"  {ok} extraer_peso_kg('{entrada}') = {resultado} (esperado: {esperado})")
    
    print("\n🧪 Tests completados")
