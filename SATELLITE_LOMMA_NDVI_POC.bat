@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Satellite V1a · Lomma NDVI pixel-PoC · 9 juli 2026
echo ==============================================================================
py -3 src\18_satellite_lomma_ndvi_poc.py --date 2026-07-09 --max-cloud 20
if errorlevel 1 python src\18_satellite_lomma_ndvi_poc.py --date 2026-07-09 --max-cloud 20
pause
