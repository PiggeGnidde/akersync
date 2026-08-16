@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync - hydrologi-preflight hela Skane
echo ============================================================
echo.
py -3 src\00_hydro_preflight_skane.py
if errorlevel 1 (
  echo.
  echo PREFLIGHT STOPPADE. Skicka utskriften ovan till ChatGPT.
  pause
  exit /b 1
)
echo.
pause
