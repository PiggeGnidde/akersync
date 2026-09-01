@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
if "%~3"=="" goto :usage
set "INPUT=%~f1"
set "AKERMINNE=%~f2"
set "GEOMETRY=%~f3"
set "OUT=%~dp0data\derived\akernorm_v1"
if not "%~4"=="" set "OUT=%~f4"

echo ========================================================================================
echo AkerNorm V1 - INDEPENDENT FULL SKANE VERIFIER - STOPPUNKT C
echo ========================================================================================
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before verification.
  git status --short
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 exit /b 1
py -3 -c "import pandas, pyarrow, geopandas, shapely" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python packages pandas, pyarrow, geopandas and shapely are required.
  exit /b 1
)
if not exist "%OUT%\manifests\full_skane_manifest.json" (
  echo FAIL: full Skane PASS manifest is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

py -3 src\84_verify_akernorm_v1_full_skane.py --input-dir "%INPUT%" --akerminne-skane-root "%AKERMINNE%" --field-geometry "%GEOMETRY%" --output-root "%OUT%" > "%OUT%\logs\stopc_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopc_verify.log"
if not "%RC%"=="0" goto :fail

echo.
echo VERIFY_AKERNORM_V1_FULL_SKANE: PASS
echo STOPPUNKT C - do not continue to web, tag, deployment or Sentinel-2 without explicit GO.
echo.
echo Return:
echo   1. %OUT%\logs\full_skane.log
echo   2. %OUT%\logs\stopc_verify.log
echo   3. %OUT%\manifests\full_skane_manifest.json
echo   4. %OUT%\qa\full_skane_qa.md
echo   5. %OUT%\qa\full_skane_qa.json
echo   6. %OUT%\qa\full_skane_status_distribution.csv
echo   7. %OUT%\qa\full_skane_reference_conservation.csv
echo   8. %OUT%\qa\full_skane_problem_rows.csv
echo   9. %OUT%\qa\full_skane_problem_fields_sample.geojson
echo  10. %OUT%\qa\full_skane_municipality_coverage.csv
echo  11. %OUT%\qa\full_skane_unsupported_coverage.csv
echo  12. %OUT%\qa\full_skane_official_vs_field.csv
echo  13. %OUT%\qa\stopc_verification.json
echo  14. Every WARN, ERROR, FAIL, MISMATCH and BLOCKED line under %OUT%\logs
exit /b 0

:usage
echo Usage:
echo   VERIFY_AKERNORM_V1_FULL_SKANE.bat "FROZEN_INPUT_DIR" "AKERMINNE_SIDECAR_ROOT" "2025_FIELD_GEOMETRY_GPKG" ["OUTPUT_ROOT"]
exit /b 2

:fail
echo.
echo VERIFY_AKERNORM_V1_FULL_SKANE: FAIL
echo Return: %OUT%\logs\stopc_verify.log
exit /b 1
