@echo off
:: ============================================================
:: run_weekly.bat — Actualización semanal automática de StackFit
:: Ejecutar desde Task Scheduler una vez por semana
:: ============================================================

cd /d "%~dp0"

:: Forzar UTF-8 en la consola
chcp 65001 >nul

set LOGFILE=%~dp0logs\weekly_%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%.log
if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [%DATE% %TIME%] === INICIO ACTUALIZACION SEMANAL === >> "%LOGFILE%" 2>&1

:: 1. Scraping
echo [%DATE% %TIME%] Paso 1: Scraping... >> "%LOGFILE%" 2>&1
python -X utf8 scraper.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR en scraper.py - abortando >> "%LOGFILE%" 2>&1
    exit /b 1
)

:: 2. Descargar imágenes nuevas
echo [%DATE% %TIME%] Paso 2: Descargando imagenes... >> "%LOGFILE%" 2>&1
python -X utf8 descargar_imagenes.py >> "%LOGFILE%" 2>&1

:: 3. Build del sitio
echo [%DATE% %TIME%] Paso 3: Build del sitio... >> "%LOGFILE%" 2>&1
python -X utf8 build.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR en build.py - abortando >> "%LOGFILE%" 2>&1
    exit /b 1
)

:: 4. Git commit y push
echo [%DATE% %TIME%] Paso 4: Git commit y push... >> "%LOGFILE%" 2>&1
git add datasets/ data/ docs/ >> "%LOGFILE%" 2>&1
git commit -m "auto: actualizar precios %DATE%" >> "%LOGFILE%" 2>&1
git push origin master >> "%LOGFILE%" 2>&1

echo [%DATE% %TIME%] === FIN OK === >> "%LOGFILE%" 2>&1
