@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Satellite V1a · Sentinel-2 preflight · juli 2026
echo ==============================================================================
py -3 src\16_satellite_preflight.py --start 2026-07-01 --end 2026-07-31
if errorlevel 1 python src\16_satellite_preflight.py --start 2026-07-01 --end 2026-07-31
pause
