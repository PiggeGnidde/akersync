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
echo AkerNorm V1 - FULL SKANE - STOPPUNKT C
echo ========================================================================================
echo Frozen input:    %INPUT%
echo AkerMinne source:%AKERMINNE%
echo Field geometry:  %GEOMETRY%
echo Output:          %OUT%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before full Skane.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akernorm-product-v1a" (
  echo FAIL: expected feature/akernorm-product-v1a, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)
py -3 -c "import pandas, pyarrow, geopandas, shapely" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python packages pandas, pyarrow, geopandas and shapely are required.
  exit /b 1
)
if not exist "%INPUT%" (
  echo FAIL: frozen input directory is missing.
  exit /b 1
)
if not exist "%AKERMINNE%" (
  echo FAIL: AkerMinne source is missing.
  exit /b 1
)
if not exist "%GEOMETRY%" (
  echo FAIL: 2025 field geometry is missing.
  exit /b 1
)
if not exist "%OUT%\manifests\model_manifest.json" (
  echo FAIL: STOPPUNKT B model manifest is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

echo [1/2] Full-Skane regression tests...
py -3 -m unittest discover -s tests -p "test_akernorm_v1_full_skane.py" -v > "%OUT%\logs\full_skane_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\full_skane_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] 33 municipality checkpointed full run...
py -3 src\83_run_akernorm_v1_full_skane.py --input-dir "%INPUT%" --akerminne-skane-root "%AKERMINNE%" --field-geometry "%GEOMETRY%" --output-root "%OUT%" > "%OUT%\logs\full_skane.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\full_skane.log"
if not "%RC%"=="0" goto :fail

echo.
echo RUN_AKERNORM_V1_FULL_SKANE: PASS
echo No web build, deployment or Sentinel-2 work ran.
echo Run the independent STOPPUNKT C verifier next.
exit /b 0

:usage
echo Usage:
echo   RUN_AKERNORM_V1_FULL_SKANE.bat "FROZEN_INPUT_DIR" "AKERMINNE_SIDECAR_ROOT" "2025_FIELD_GEOMETRY_GPKG" ["OUTPUT_ROOT"]
exit /b 2

:fail
echo.
echo RUN_AKERNORM_V1_FULL_SKANE: FAIL
echo Return: %OUT%\logs\full_skane_tests.log, %OUT%\logs\full_skane.log and any *_traceback.log
exit /b 1
