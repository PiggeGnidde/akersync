@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ================================================================
echo ÅkerSwap Lab v0a - virtuella bönder via fältklick
echo ================================================================

py -3 tools\build_akerswap_lab_v0a.py
if errorlevel 1 exit /b 1

set "PORT=8013"
echo.
echo Startar lokal ÅkerSwap Lab på http://localhost:%PORT%/
start "ÅkerSwap Lab Server" cmd /k "cd /d %CD% && py -3 -m http.server %PORT% --directory dist_akerswap_lab_v0a"
timeout /t 2 /nobreak >nul
start "" "http://localhost:%PORT%/"
echo.
echo Testa: Bonde A - klicka skiften - Bonde B - klicka skiften - Kopiera A/B.
echo Den frysta ÅkerPass-källan ändras inte.
exit /b 0
