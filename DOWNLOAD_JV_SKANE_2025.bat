@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync - hamta komplett Jordbruksverket Skane 2025
echo ============================================================
echo.
py -3 src\00_download_jv_skane_2025.py
if errorlevel 1 (
  echo.
  echo NEDLADDNING MISSLYCKADES. Skicka sista felraderna till ChatGPT.
  exit /b 1
)
echo.
echo KLART. Kor SET_JV_SKANE_2025.bat som nasta steg.
