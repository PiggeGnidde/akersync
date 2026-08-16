@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync - granska saknade DEM core-rutor
echo ============================================================
echo.
py -3 src\00_inspect_dem_core_gaps.py
if errorlevel 1 (
  echo.
  echo CORE-AUDIT MISSLYCKADES. Skicka utskriften ovan till ChatGPT.
  exit /b 1
)
