@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT F TRANSPARENT CANDIDATE COMPONENTS
echo ====================================================================================================
echo.
echo Candidate scales only:
echo   MarkTorka
echo   MarkVata
echo   GrundvattenTillgang
echo   GrundvattenTorka
echo   YtvattenTorka
echo.
echo No combined AkerVatten index is created.
echo Historical groundwater/surface percentiles are defined over unique hydrological units before field join.
echo Missing primary inputs are NOT silently reweighted.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

echo [preflight] Python dependencies...
py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 (
  echo FAIL: F requires pandas numpy pyarrow.
  exit /b 1
)

echo.
echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_f_component_candidates -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Candidate component transforms...
py -3 src\100_akervatten_f_component_candidates.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_F_COMPONENT_CANDIDATES: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before F is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_F_COMPONENT_CANDIDATES: FAIL
echo ====================================================================================================
exit /b 1
