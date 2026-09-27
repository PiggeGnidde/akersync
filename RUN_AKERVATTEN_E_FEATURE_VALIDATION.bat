@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT E CANDIDATE FEATURE VALIDATION
echo ====================================================================================================
echo.
echo Diagnostic only:
echo   - field-weighted vs hydrological-unit-weighted distributions
echo   - within-family Spearman correlations
echo   - directional top-decile overlap
echo   - cross-family correlations
echo   - directional extreme cases for manual/map sanity checks
echo No component score and no combined score is frozen here.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

echo [preflight] Python dependencies...
py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 (
  echo.
  echo FAIL: E requires pandas numpy pyarrow.
  echo Paste the complete import error back to the coding chat.
  exit /b 1
)

echo.
echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_e_feature_validation -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Candidate feature validation...
py -3 src\98_akervatten_e_feature_validation.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_E_FEATURE_VALIDATION: PASS
echo ====================================================================================================
echo Paste the CMD output back to the coding chat. E is PASS_WITH_REVIEW until candidate choices are reviewed.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_E_FEATURE_VALIDATION: FAIL
echo ====================================================================================================
exit /b 1
