@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten H1 - YSTAD / LODERUP HYDROLOGY REVIEW
echo ====================================================================================================
echo.
echo Compares two exact Ystad extreme fields with the Loderups Vaxt address reference.
echo Checks SGU large magazines, subareas, recharge areas, SGU-HYPE, SVAR ARO_UUID and S-HYPE Subid.
echo No score is created or modified.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,geopandas,pyarrow,pyproj,numpy"
if errorlevel 1 exit /b 1

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_h1_ystad_loderup_review -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Focused hydrology review...
py -3 src\109_akervatten_h1_ystad_loderup_review.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_H1_YSTAD_LODERUP_REVIEW: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before H0/H1 interpretation or freeze.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_H1_YSTAD_LODERUP_REVIEW: FAIL
echo ====================================================================================================
exit /b 1
