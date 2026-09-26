@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - C10 TRANSPARENT OPERATIONAL LAYER
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

if not exist "data\derived\akerfro_ertor_v0a\artkandidat_v0a_fields.parquet" (
  echo FEL: C8 product saknas.
  exit /b 1
)

if not exist "work\akerfro_ertor_v0a\area_logistics_c9\artkandidat_c9_area_logistics_fields.parquet" (
  echo FEL: C9 sidecar saknas. Kor C9 forst.
  exit /b 1
)

py -3 -m unittest tests.test_akerfro_operational_c10 -v
if errorlevel 1 goto :fail

py -3 analysis\akerfro_ertor_v0a\operational_c10.py
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo ==============================================================================
echo C10 TRANSPARENT OPERATIONAL LAYER: FAIL
echo ==============================================================================
exit /b 1
