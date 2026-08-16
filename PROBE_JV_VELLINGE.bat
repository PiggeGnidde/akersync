@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync - Jordbruksverket WFS probe Vellinge 2025
echo ============================================================
echo.
py -3 src\00_probe_jv_vellinge.py
if errorlevel 1 (
  echo.
  echo PROBE MISSLYCKADES. Skicka utskriften till ChatGPT.
  pause
  exit /b 1
)
echo.
pause
