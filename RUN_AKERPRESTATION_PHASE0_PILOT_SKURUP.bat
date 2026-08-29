@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1

cd /d "%~dp0"
set "ROOT=%CD%"
set "PHASE=data\derived\akerprestation_phase0"
set "LOGDIR=%PHASE%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ==============================================================================
echo AkerPrestation phase 0 - SKURUP PILOT ONLY - STOPPUNKT B
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

git status --short > "%TEMP%\akerprestation_phase0_status.txt"
for %%A in ("%TEMP%\akerprestation_phase0_status.txt") do if %%~zA GTR 0 (
  echo ERROR: Git working tree is not clean before pilot.
  type "%TEMP%\akerprestation_phase0_status.txt"
  exit /b 1
)

if not exist "config\local_paths.json" (
  echo ERROR: config\local_paths.json missing.
  exit /b 1
)
if not exist "%PHASE%\manifests\discovery_manifest.json" (
  echo ERROR: discovery manifest missing. STOPPUNKT A must be completed first.
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
echo [1/4] Synthetic overlay + frozen ÅkerMinne locator tests...
py -3 -m unittest discover -s tests -p "test_akerprestation_phase0_*.py" -v > "%LOGDIR%\pilot_overlay_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOGDIR%\pilot_overlay_tests.log"
if not "%RC%"=="0" (
  echo.
  echo PILOT RUNNER: FAIL - synthetic tests
  exit /b %RC%
)

echo.
echo [2/4] Skurup exact overlay - live progress every 250 fields...
py -3 src\71b_akerprestation_phase0_pilot.py --municipality Skurup --municipality-code 1264 --layers soil_class,sko --resume --progress-every 250
if errorlevel 1 (
  echo.
  echo PILOT RUNNER: FAIL - overlay/integration
  exit /b 1
)

echo.
echo [3/4] Resume self-test - both validated layer checkpoints must be reused...
py -3 src\71b_akerprestation_phase0_pilot.py --municipality Skurup --municipality-code 1264 --layers soil_class,sko --resume --resume-probe --progress-every 250
if errorlevel 1 (
  echo.
  echo PILOT RUNNER: FAIL - resume self-test
  exit /b 1
)

echo.
echo [4/4] Independent pilot verification...
py -3 src\72_verify_akerprestation_phase0_pilot.py
if errorlevel 1 (
  echo.
  echo PILOT RUNNER: FAIL - verification
  exit /b 1
)

git status --short > "%TEMP%\akerprestation_phase0_status_after.txt"
for %%A in ("%TEMP%\akerprestation_phase0_status_after.txt") do if %%~zA GTR 0 (
  echo ERROR: Git working tree changed during pilot.
  type "%TEMP%\akerprestation_phase0_status_after.txt"
  exit /b 1
)

echo.
echo ==============================================================================
echo PILOT RUNNER: PASS
echo ==============================================================================
echo Progress skrivs live per 250 Skurup-skiften.
echo Framtida Skane-runner ar konfigurerad for progress minst per kommun och var 5000:e skifte.
echo Ingen Skane-korning, webb, satellit eller skordemodell har korts.
echo.
echo STOPPUNKT B - returnera:
echo   1. Hela PASS/FAIL-sammanfattningen ovan
echo   2. data\derived\akerprestation_phase0\pilot_skurup\phase0_pilot_qa.md
echo   3. data\derived\akerprestation_phase0\pilot_skurup\phase0_pilot_qa.json
echo   4. data\derived\akerprestation_phase0\pilot_skurup\akerminne_context_join_qa.json
echo   5. data\derived\akerprestation_phase0\pilot_skurup\problem_fields.geojson eller kartbilder
echo   6. data\derived\akerprestation_phase0\pilot_skurup\manual_checklist.json
echo   7. Alla WARN och ERROR-rader ur:
echo      data\derived\akerprestation_phase0\logs\pilot_skurup.log
echo      data\derived\akerprestation_phase0\logs\pilot_skurup_resume_probe.log
echo.
exit /b 0
