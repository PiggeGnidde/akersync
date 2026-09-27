@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d %~dp0

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT F5 FINAL COMPONENT CANDIDATE
echo ====================================================================================================
echo.
for /f "delims=" %%B in ('git branch --show-current') do set BRANCH=%%B
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 exit /b 1

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_f5_final_candidate -v
if errorlevel 1 goto fail

echo.
echo [2/2] Final candidate assembly...
py -3 src\104_akervatten_f5_final_candidate.py
if errorlevel 1 goto fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_F5_FINAL_CANDIDATE: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before F is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_F5_FINAL_CANDIDATE: FAIL
echo ====================================================================================================
exit /b 1
