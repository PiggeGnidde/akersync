@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
set "PHASE=data\derived\akerprestation_phase0"
set "LOGDIR=%PHASE%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ==============================================================================
echo AkerPrestation phase 0 - FULL SKANE DATA RUN - STOPPUNKT C
echo ==============================================================================

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerprestation-foundation-v0a" (
  echo ERROR: Expected branch feature/akerprestation-foundation-v0a, got %BRANCH%
  exit /b 1
)

git merge-base --is-ancestor 4b53ab24e9822f1c36c6cc31931dba3c1855fead HEAD
if errorlevel 1 (
  echo ERROR: HEAD does not descend from frozen akerminne-v1.0 commit.
  exit /b 1
)

git status --short > "%TEMP%\akerprestation_phase0_skane_status.txt"
for %%A in ("%TEMP%\akerprestation_phase0_skane_status.txt") do if %%~zA GTR 0 (
  echo ERROR: Git working tree is not clean before Skane run.
  type "%TEMP%\akerprestation_phase0_skane_status.txt"
  exit /b 1
)

if not exist "config\local_paths.json" (
  echo ERROR: config\local_paths.json missing.
  exit /b 1
)
if not exist "%PHASE%\pilot_skurup\phase0_pilot_qa.json" (
  echo ERROR: STOPPUNKT B pilot QA missing.
  exit /b 1
)
if not exist "%PHASE%\qa\real_class123\qa.json" (
  echo ERROR: STOPPUNKT B.1 real class 1/2/3 QA missing.
  exit /b 1
)
if not exist "%PHASE%\discovery\source\jord_skogsklassificering_class1_10.gpkg" (
  echo ERROR: soil discovery cache missing.
  exit /b 1
)
if not exist "%PHASE%\discovery\source\jordbruksverket_sko.gpkg" (
  echo ERROR: SKO discovery cache missing.
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python launcher py not found.
  exit /b 1
)

echo.
echo [1/3] Phase 0 test suite...
py -3 -m unittest discover -s tests -p "test_akerprestation_phase0_*.py" -v > "%LOGDIR%\skane_phase0_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOGDIR%\skane_phase0_tests.log"
if not "%RC%"=="0" (
  echo.
  echo SKANE RUNNER: FAIL - tests
  exit /b %RC%
)

echo.
echo [2/3] Full Skane static overlay - checkpointed per municipality/layer...
echo       Progress: municipality PASS/FAIL plus every 5000 fields inside each layer.
py -3 src\74_run_akerprestation_phase0_skane.py --resume --progress-every 5000
if errorlevel 1 (
  echo.
  echo SKANE RUNNER: FAIL - county overlay/QA
  exit /b 1
)

echo.
echo [3/3] Independent county verification...
py -3 src\75_verify_akerprestation_phase0_skane.py
if errorlevel 1 (
  echo.
  echo SKANE RUNNER: FAIL - independent verification
  exit /b 1
)

git status --short > "%TEMP%\akerprestation_phase0_skane_status_after.txt"
for %%A in ("%TEMP%\akerprestation_phase0_skane_status_after.txt") do if %%~zA GTR 0 (
  echo ERROR: Git working tree changed during Skane run.
  type "%TEMP%\akerprestation_phase0_skane_status_after.txt"
  exit /b 1
)

echo.
echo ==============================================================================
echo SKANE RUNNER: PASS
echo ==============================================================================
echo Alla 33 kommuner har validerats separat och totalsumman har verifierats.
echo Checkpoints ar separata per kommun och lager; giltiga checkpoints ateranvands.
echo Ingen webb, tagg, merge, satellit, normskord eller prestationsmodell har korts.
echo.
echo STOPPUNKT C - returnera:
echo   1. Hela PASS/FAIL-sammanfattningen
echo   2. %PHASE%\qa\skane\qa.md
echo   3. %PHASE%\qa\skane\qa.json
echo   4. %PHASE%\manifests\skane_phase0_manifest.json
echo   5. %PHASE%\qa\skane\municipality_qa.csv
echo   6. %PHASE%\qa\skane\soil_class_by_municipality.csv
echo   7. %PHASE%\qa\skane\sko_distribution.csv
echo   8. %PHASE%\qa\skane\problem_fields.geojson
echo   9. Alla WARN och ERROR ur %PHASE%\logs\skane_phase0.log
echo.
echo Alla SKO-gransfalt finns i:
echo   %PHASE%\skane\sko_boundary_fields.parquet
echo   %PHASE%\skane\sko_boundary_fields.geojson
echo.
exit /b 0
