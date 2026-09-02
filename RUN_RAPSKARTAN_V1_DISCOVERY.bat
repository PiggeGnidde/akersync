@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/rapskartan-skane-v1a"
set "UPSTREAM_TAG=akernorm-v1.0"
set "UPSTREAM_TAG_OBJECT=c7f8022f13ef1fdc4560ce906e9a10c467f15c0f"
set "UPSTREAM_COMMIT=c859a69de51a104d10f87906d4d050a34222bbb4"
set "SOURCE_REPO=C:\AkerSyncRepo"
set "INPUT=%SOURCE_REPO%\work\akerscore_validation_csv_upload"
set "RAW_ROOT=C:\AkerSyncRaw"
set "LOCAL_PATHS=%SOURCE_REPO%\config\local_paths.json"
set "OUT=%SOURCE_REPO%\work\rapskartan_skane_v1_discovery_stopA"

if not "%~1"=="" set "INPUT=%~1"
if not "%~2"=="" set "RAW_ROOT=%~2"
if not "%~3"=="" set "LOCAL_PATHS=%~3"
if not "%~4"=="" set "OUT=%~4"

echo ========================================================================================
echo Rapskartan Skane V1 - DISCOVERY ONLY - STOPPUNKT A
echo ========================================================================================
echo Frozen input: %INPUT%
echo Raw root:     %RAW_ROOT%
echo Local paths: %LOCAL_PATHS%
echo Output:       %OUT%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before discovery.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
for /f "delims=" %%T in ('git cat-file -t "%UPSTREAM_TAG%"') do set "TAG_TYPE=%%T"
if /I not "%TAG_TYPE%"=="tag" (
  echo FAIL: %UPSTREAM_TAG% is not an annotated tag.
  exit /b 1
)
for /f "delims=" %%T in ('git rev-parse "%UPSTREAM_TAG%"') do set "TAG_OBJECT=%%T"
if /I not "%TAG_OBJECT%"=="%UPSTREAM_TAG_OBJECT%" (
  echo FAIL: tag object mismatch: %TAG_OBJECT%
  exit /b 1
)
for /f "delims=" %%T in ('git rev-list -n 1 "%UPSTREAM_TAG%"') do set "TAG_COMMIT=%%T"
if /I not "%TAG_COMMIT%"=="%UPSTREAM_COMMIT%" (
  echo FAIL: dereferenced tag commit mismatch: %TAG_COMMIT%
  exit /b 1
)
git merge-base --is-ancestor "%UPSTREAM_COMMIT%" HEAD
if errorlevel 1 (
  echo FAIL: upstream freeze is not an ancestor of HEAD.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/2] Discovery contracts and blind-guard tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery -v > "%OUT%\logs\discovery_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\discovery_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Repository, ground truth, geometry and minimal Sentinel-2 access...
py -3 src\90_run_rapskartan_v1_discovery.py --input-dir "%INPUT%" --raw-root "%RAW_ROOT%" --local-paths "%LOCAL_PATHS%" --output-dir "%OUT%" > "%OUT%\logs\discovery_full.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\discovery_full.log"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUT%\discovery_repository_report.md"
  "%OUT%\crop_ground_truth_inventory.csv"
  "%OUT%\crop_code_contract.json"
  "%OUT%\geometry_lineage.md"
  "%OUT%\satellite_access_report.md"
  "%OUT%\temporal_cutoff_contract.json"
  "%OUT%\cache_storage_estimate.json"
  "%OUT%\discovery_qa.md"
  "%OUT%\discovery_manifest.json"
) do if not exist "%%~F" (
  echo FAIL: required STOPPUNKT A artifact is missing: %%~F
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: discovery changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo RAPSKARTAN SKANE V1 DISCOVERY RUNNER: PASS
echo ========================================================================================
echo No classifier, mass download, Sentinel-1, web or deployment ran.
echo Run next:
echo   VERIFY_RAPSKARTAN_V1_DISCOVERY.bat "%OUT%"
echo.
echo STOPPUNKT A - return the complete logs and artifacts listed by the verifier.
exit /b 0

:fail
echo.
echo ========================================================================================
echo RAPSKARTAN SKANE V1 DISCOVERY RUNNER: FAIL OR BLOCKED
echo ========================================================================================
echo If the log says BLOCKED_CREDENTIALS, set CDSE_CLIENT_ID and CDSE_CLIENT_SECRET locally and rerun.
echo Never paste the client secret into chat or commit it to Git.
echo Return all files under: %OUT%\logs
exit /b 1
