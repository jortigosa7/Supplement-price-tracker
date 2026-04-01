# 🏋️ Supplement Price Scraper - Dataset Business

## Proyecto de Javier: Scraping de precios de suplementos fitness

### ¿Qué hace este proyecto?
Scrapea precios de suplementos deportivos (proteínas, creatina, etc.) de varias
tiendas online españolas y genera un dataset limpio en CSV y JSON.

---

### Setup rápido (Windows + VS Code)

#### 1. Abre PowerShell o la terminal de VS Code y navega a la carpeta del proyecto:
```powershell
cd C:\Users\TU_USUARIO\Desktop\supplement-scraper
```

#### 2. Crea un entorno virtual (buena práctica):
```powershell
python -m venv venv
venv\Scripts\activate
```

#### 3. Instala las dependencias:
```powershell
pip install -r requirements.txt
```

#### 4. Ejecuta el scraper:
```powershell
python scraper.py
```

#### 5. Revisa los resultados en la carpeta `datasets/`

---

### Estructura del proyecto
```
supplement-scraper/
├── README.md                 # Este archivo
├── requirements.txt          # Dependencias de Python
├── scraper.py               # Script principal del scraper
├── limpieza.py              # Funciones de limpieza de datos
├── analisis.py              # Análisis exploratorio (para el portfolio)
└── datasets/                # Aquí se guardan los CSV y JSON generados
```

---

### Tiendas que scrapeamos
| Tienda       | Método            | Dificultad |
|-------------|-------------------|------------|
| Nutritienda | HTML estático     | Fácil      |
| HSN         | JSON embebido     | Media      |
| Amazon ES   | Estructura HTML   | Media      |

---

### Próximos pasos
1. ✅ Scraper básico funcionando
2. ⬜ Añadir más tiendas (MyProtein, iHerb)
3. ⬜ Automatizar con cron/n8n
4. ⬜ Subir dataset a Gumroad + Kaggle
5. ⬜ Análisis exploratorio para portfolio
6. ⬜ Web comparadora con afiliación
