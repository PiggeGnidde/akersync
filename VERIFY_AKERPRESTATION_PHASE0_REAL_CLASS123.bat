@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1

cd /d "%~dp0"
set "PHASE=data\derived\akerprestation_phase0"
set "LOGDIR=%PHASE%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ==============================================================================
echo AkerPrestation phase 0 - REAL CLASS 1/2/3 GATE ONLY - STOPPUNKT B.1
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

git status --short > "%TEMP%\akerprestation_class123_status.txt"
for %%A in ("%TEMP%\akerprestation_class123_status.txt") do if %%~zA GTR 0 (
  echo ERROR: Git working tree is not clean before real class 1/2/3 gate.
  type "%TEMP%\akerprestation_class123_status.txt"
  exit /b 1
)

if not exist "config\local_paths.json" (
  echo ERROR: config\local_paths.json missing.
  exit /b 1
)
if not exist "%PHASE%\discovery\source\jord_skogsklassificering_class1_10.gpkg" (
  echo ERROR: approved class 1-10 discovery cache missing.
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python launcher py not found.
  exit /b 1
)

echo.
echo [1/2] Focused unit tests...
py -3 -m unittest discover -s tests -p "test_akerprestation_phase0_real_class123.py" -v > "%LOGDIR%\real_class123_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOGDIR%\real_class123_tests.log"
if not "%RC%"=="0" (
  echo.
  echo REAL CLASS 1/2/3 RUNNER: FAIL - unit tests
  exit /b %RC%
)

echo.
echo [2/2] Real-source exact overlay gate - 5 fields each for dominant class 1, 2 and 3...
py -3 src\73_verify_akerprestation_phase0_real_class123.py > "%LOGDIR%\real_class123.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOGDIR%\real_class123.log"
if not "%RC%"=="0" (
  echo.
  echo REAL CLASS 1/2/3 RUNNER: FAIL - integration gate
  exit /b %RC%
)

git status --short > "%TEMP%\akerprestation_class123_status_after.txt"
for %%A in ("%TEMP%\akerprestation_class123_status_after.txt") do if %%~zA GTR 0 (
  echo ERROR: Git working tree changed during real class 1/2/3 gate.
  type "%TEMP%\akerprestation_class123_status_after.txt"
  exit /b 1
)

echo.
echo ==============================================================================
echo REAL CLASS 1/2/3 RUNNER: PASS
echo ==============================================================================
echo Exactly 15 real 2025 fields tested outside Skurup: 5 dominant class 1, 5 class 2, 5 class 3.
echo No municipality batch, no Skane batch, no SKO recomputation and no web phase executed.
echo.
echo STOPPUNKT B.1 - returnera:
echo   1. Hela konsoloutputen ovan
echo   2. data\derived\akerprestation_phase0\qa\real_class123\qa.md
echo   3. data\derived\akerprestation_phase0\qa\real_class123\qa.json
echo   4. data\derived\akerprestation_phase0\qa\real_class123\selected_fields.geojson
echo   5. Alla WARN och ERROR ur data\derived\akerprestation_phase0\logs\real_class123.log
echo.
exit /b 0
