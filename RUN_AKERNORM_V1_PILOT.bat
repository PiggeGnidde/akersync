@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
set "INPUT=%~f1"
set "AKERMINNE=%~f2"
set "OUT=%~dp0data\derived\akernorm_v1"
if not "%~3"=="" set "OUT=%~f3"

echo ========================================================================================
echo AkerNorm V1 - BOUNDED PRODUCTION PILOT - STOPPUNKT B
echo ========================================================================================
echo Frozen input:  %INPUT%
echo AkerMinne source: %AKERMINNE%
echo Output:        %OUT%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before pilot.
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
if not exist "%OUT%\manifests\model_manifest.json" (
  echo FAIL: model freeze PASS artifact is missing. Run FREEZE_AKERNORM_V1_MODEL.bat first.
  exit /b 1
)
if not exist "%AKERMINNE%" (
  echo FAIL: frozen AkerMinne source is missing: %AKERMINNE%
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

echo [1/2] Pilot selection and calculation regression tests...
py -3 -m unittest discover -s tests -p "test_akernorm_v1_pilot.py" -v > "%OUT%\logs\pilot_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\pilot_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Bounded production pilot on frozen inputs...
py -3 src\81_run_akernorm_v1_pilot.py --input-dir "%INPUT%" --akerminne-skane-root "%AKERMINNE%" --output-root "%OUT%" > "%OUT%\logs\pilot.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\pilot.log"
if not "%RC%"=="0" goto :fail

echo.
echo RUN_AKERNORM_V1_PILOT: PASS
echo No full Skane field run, web build or Sentinel-2 work ran.
echo.
echo Run next:
echo   VERIFY_AKERNORM_V1_PILOT.bat "%OUT%"
exit /b 0

:usage
echo Usage:
echo   RUN_AKERNORM_V1_PILOT.bat "FROZEN_INPUT_DIR" "AKERMINNE_SKANE_OR_SIDECAR_ROOT" ["OUTPUT_ROOT"]
exit /b 2

:fail
echo.
echo RUN_AKERNORM_V1_PILOT: FAIL
echo Return: %OUT%\logs\pilot_tests.log, %OUT%\logs\pilot.log and any *_traceback.log
exit /b 1
