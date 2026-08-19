@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo AkerPass visas pa http://localhost:8000/
echo Stoppa servern med Ctrl+C.
echo.
py -3 -m http.server 8000 --directory dist
if errorlevel 1 python -m http.server 8000 --directory dist
