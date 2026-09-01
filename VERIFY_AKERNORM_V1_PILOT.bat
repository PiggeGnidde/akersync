@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=%~dp0data\derived\akernorm_v1"
if not "%~1"=="" set "OUT=%~f1"

echo ========================================================================================
echo AkerNorm V1 - INDEPENDENT STOPPUNKT B VERIFIER
echo ========================================================================================
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before verification.
  git status --short
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 exit /b 1
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

py -3 src\82_verify_akernorm_v1_pilot.py --output-root "%OUT%" > "%OUT%\logs\stopb_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopb_verify.log"
if not "%RC%"=="0" goto :fail

echo.
echo VERIFY_AKERNORM_V1_PILOT: PASS
echo STOPPUNKT B - do not continue to full Skane or web without explicit GO.
echo.
echo Return:
echo   1. %OUT%\logs\model_freeze.log
echo   2. %OUT%\logs\pilot.log
echo   3. %OUT%\logs\stopb_verify.log
echo   4. %OUT%\model\akernorm_model_contract_v1.json
echo   5. %OUT%\source\normalized\official_norm_yield_2026_normalized.csv
echo   6. %OUT%\model\sko_crop_score_reference.csv
echo   7. %OUT%\pilot\field_akernorm_v1_pilot.csv
echo   8. %OUT%\qa\model_reproduction_qa.md
echo   9. %OUT%\qa\pilot_qa.md
echo  10. %OUT%\qa\pilot_invariants.csv
echo  11. %OUT%\qa\pilot_example_calculations.csv
echo  12. Every WARN, ERROR, FAIL, MISMATCH and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo VERIFY_AKERNORM_V1_PILOT: FAIL
echo Return: %OUT%\logs\stopb_verify.log
exit /b 1
