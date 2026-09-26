@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - C8b + C9 AREA / BJUV LOGISTICS
echo ==============================================================================

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

echo.
echo [1/3] Rebuild C8 with stricter predecessor support...
CALL RUN_AKERFRO_ERTOR_C8_ARTKANDIDAT.bat
if errorlevel 1 goto :fail

echo.
echo [2/3] Run C9 unit tests...
py -3 -m unittest tests.test_akerfro_area_logistics_c9 -v
if errorlevel 1 goto :fail

echo.
echo [3/3] Run C9 area + Bjuv logistics diagnostic...
py -3 analysis\akerfro_ertor_v0a\area_logistics_c9.py
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo ==============================================================================
echo C8b + C9 AREA / BJUV LOGISTICS: FAIL
echo ==============================================================================
exit /b 1
