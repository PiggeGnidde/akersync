@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
set "STOPA=%~f1"
set "INPUT=%~f2"
set "OUT=%~dp0data\derived\akernorm_v1"
if not "%~3"=="" set "OUT=%~f3"

echo ========================================================================================
echo AkerNorm V1 - FREEZE MODEL CANDIDATE - PHASE B
echo ========================================================================================
echo STOPPUNKT A: %STOPA%
echo Frozen input: %INPUT%
echo Output:        %OUT%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before model freeze.
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
if not exist "%STOPA%\discovery_manifest.json" (
  echo FAIL: STOPPUNKT A manifest is missing.
  exit /b 1
)
if not exist "%INPUT%\field_static_context_selected.csv.gz" (
  echo FAIL: frozen compact input package is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/2] Model unit and invariant tests...
py -3 -m unittest discover -s tests -p "test_akernorm_v1_model.py" -v > "%OUT%\logs\model_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\model_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Freeze official source, references and model contract...
py -3 src\80_freeze_akernorm_v1_model.py --stop-a-dir "%STOPA%" --input-dir "%INPUT%" --output-root "%OUT%" > "%OUT%\logs\model_freeze.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\model_freeze.log"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUT%\manifests\source_manifest.json"
  "%OUT%\manifests\model_manifest.json"
  "%OUT%\model\akernorm_model_contract_v1.json"
  "%OUT%\model\sko_crop_score_reference.csv"
  "%OUT%\model\reference_conservation_qa.csv"
  "%OUT%\qa\model_reproduction_qa.md"
) do if not exist "%%~F" (
  echo FAIL: required model artifact is missing: %%~F
  goto :fail
)
echo.
echo FREEZE_AKERNORM_V1_MODEL: PASS
echo Next: run the bounded pilot. This runner did not run full Skane or web.
exit /b 0

:usage
echo Usage:
echo   FREEZE_AKERNORM_V1_MODEL.bat "STOPPUNKT_A_DIR" "FROZEN_INPUT_DIR" ["OUTPUT_ROOT"]
exit /b 2

:fail
echo.
echo FREEZE_AKERNORM_V1_MODEL: FAIL
echo Return: %OUT%\logs\model_tests.log and %OUT%\logs\model_freeze.log
exit /b 1
