@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync reproducible build - RAW DATA to v0.92
echo ============================================================
echo.
py -3 src\build_all.py
if errorlevel 1 (
  echo.
  echo BUILD MISSLYCKADES. Skicka sista felraderna till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART: dist\index.html
pause
