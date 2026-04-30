@echo off
cd /d "C:\Users\Javier\Desktop\supplement-scraper\files (1)"
python scraper.py >> logs\scraper.log 2>&1
if %errorlevel% equ 0 (
    python build.py >> logs\build.log 2>&1
    git add docs/ data/ datasets/
    git commit -m "auto: actualizar precios"
    git push origin master
)
