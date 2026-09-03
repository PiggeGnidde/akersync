@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/rapskartan-skane-v1a"
set "RAW_ROOT=C:\AkerSyncRaw"
set "STOP_C=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "STOP_D=C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"
set "OUT=%~dp0data\derived\rapskartan_v1\2025"
set "ARCHIVE=C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\map_product_2025_scene_archive_v1"
if not "%~1"=="" set "RAW_ROOT=%~1"
if not "%~2"=="" set "OUT=%~2"
if not "%~3"=="" set "ARCHIVE=%~3"
if not "%~4"=="" set "STOP_C=%~4"
if not "%~5"=="" set "STOP_D=%~5"

echo ========================================================================================
echo Rapskartan Skane V1 - FULL HISTORICAL 2025 MAP PRODUCT - STOPPUNKT E
echo ========================================================================================
echo Raw root:       %RAW_ROOT%
echo Accepted StopC: %STOP_C%
echo Accepted StopD: %STOP_D%
echo Product output: %OUT%
echo Scene archive: %ARCHIVE%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before map generation.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)
if "%AWS_ACCESS_KEY_ID%"=="" (
  echo BLOCKED_S3_CREDENTIALS: AWS_ACCESS_KEY_ID is not set in this cmd.exe window.
  exit /b 1
)
if "%AWS_SECRET_ACCESS_KEY%"=="" (
  echo BLOCKED_S3_CREDENTIALS: AWS_SECRET_ACCESS_KEY is not set in this cmd.exe window.
  exit /b 1
)
py -3 -c "import affine, boto3, geopandas, joblib, numpy, pandas, pyarrow, rasterio, shapely, sklearn" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python needs affine, boto3, geopandas, joblib, numpy, pandas, pyarrow, rasterio, shapely and scikit-learn.
  exit /b 1
)
if not exist "%STOP_C%\model_artifacts_manifest.json" (
  echo FAIL: accepted STOPPUNKT C model manifest is missing.
  exit /b 1
)
if not exist "%STOP_D%\blind_evaluation_manifest.json" (
  echo FAIL: accepted STOPPUNKT D evaluation manifest is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/2] Frozen model, blind gate, local-engine and product-rule tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery tests.test_rapskartan_s2_pilot tests.test_rapskartan_model_dataset tests.test_rapskartan_model_training tests.test_rapskartan_2025_blind_prediction tests.test_rapskartan_2025_blind_evaluation tests.test_rapskartan_map_product -v > "%OUT%\logs\map_product_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\map_product_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Hash-verified scene archive, parity gate and restartable full-Skane product...
echo First run downloads up to 200 GiB and can take many hours. Municipality checkpoints survive a later failure.
powershell -NoProfile -Command "& { py -3 -u src\100_generate_rapskartan_2025_map_product.py --raw-root '%RAW_ROOT%' --stop-c-dir '%STOP_C%' --stop-d-dir '%STOP_D%' --output-dir '%OUT%' --scene-archive '%ARCHIVE%' 2>&1 | Tee-Object -FilePath '%OUT%\logs\map_product.log'; exit $LASTEXITCODE }"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail
if not exist "%OUT%\full_map_manifest.json" (
  echo FAIL: full map manifest is missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: map-product run changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo RAPSKARTAN 2025 MAP PRODUCT RUNNER: PASS
echo ========================================================================================
echo Ground truth was not included. No model/threshold tuning, web, Sentinel-1, deployment, tag or merge ran.
echo Run next:
echo   VERIFY_RAPSKARTAN_2025_MAP_PRODUCT.bat "%OUT%" "%STOP_C%" "%STOP_D%"
echo.
echo STOPPUNKT E - return the complete logs and artifacts listed by the verifier.
exit /b 0

:fail
echo.
echo ========================================================================================
echo RAPSKARTAN 2025 MAP PRODUCT RUNNER: FAIL OR BLOCKED
echo ========================================================================================
echo No web, Sentinel-1, deployment, tag or merge ran.
echo Cached scene assets and completed municipality checkpoints remain reusable.
echo Return every file under: %OUT%\logs
exit /b 1
