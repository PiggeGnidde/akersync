@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - C9b AREA / LOGISTICS ROBUSTNESS
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

if not exist "work\akerfro_ertor_v0a\area_logistics_c9\artkandidat_c9_area_logistics_fields.parquet" (
  echo FEL: C9 sidecar saknas. Kor RUN_AKERFRO_ERTOR_C9_AREA_LOGISTICS.bat forst.
  exit /b 1
)

py -3 -m unittest tests.test_akerfro_area_logistics_robustness_c9b -v
if errorlevel 1 goto :fail

py -3 analysis\akerfro_ertor_v0a\area_logistics_robustness_c9b.py
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo ==============================================================================
echo C9b AREA / LOGISTICS ROBUSTNESS: FAIL
echo ==============================================================================
exit /b 1
