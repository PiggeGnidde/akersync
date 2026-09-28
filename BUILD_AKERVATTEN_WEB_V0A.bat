@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "BASE=C:\AkerSync-AkerFroWeb\dist"
set "WATER=C:\AkerSync-Vatten"
set "DIST=%~dp0dist"
set "WORK=%~dp0work\akervatten_web_v0a"

if not "%~1"=="" set "BASE=%~f1"
if not "%~2"=="" set "WATER=%~f2"
if not "%~3"=="" set "DIST=%~f3"

echo ========================================================================================
echo AkerVatten WEB v0a - BUILD ON LATEST AKERFRO MAP
echo ========================================================================================
echo AkerFro base : %BASE%
echo Water source : %WATER%
echo Target dist  : %DIST%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before web build.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-web-v0a" (
  echo FAIL: expected feature/akervatten-web-v0a, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)
py -3 -c "import pandas, geopandas, pyarrow, numpy"
if errorlevel 1 (
  echo FAIL: pandas/geopandas/pyarrow/numpy are required.
  exit /b 1
)

if not exist "%BASE%\index.html" (
  echo FAIL: latest AkerFro base index.html missing.
  exit /b 1
)
if not exist "%BASE%\data\akerfro\skane_index.json" (
  echo FAIL: base dist is not the completed AkerFro web.
  exit /b 1
)
if not exist "%WATER%\work\akervatten_mvp_v0a\h2_product_dimensions\akervatten_h2_field_water_dimensions_skane.parquet" (
  echo FAIL: H2 product table missing in AkerVatten worktree.
  exit /b 1
)
if not exist "%WATER%\work\akervatten_mvp_v0a\h2_product_dimensions\h2_summary.json" (
  echo FAIL: H2 summary missing in AkerVatten worktree.
  exit /b 1
)

echo [1/3] Web regression tests...
py -3 -m unittest tests.test_akervatten_web_v0a -v
if errorlevel 1 goto :fail

echo.
echo [2/3] Build AkerVatten data + regional map layers + UI...
for /f "delims=" %%H in ('git rev-parse HEAD') do set "AKERVATTEN_WEB_REPOSITORY_HEAD=%%H"
py -3 src\111_build_akervatten_web_v0a.py --base-dist "%BASE%" --water-root "%WATER%" --dist "%DIST%" --work "%WORK%"
if errorlevel 1 goto :fail

echo.
echo [3/3] Independent web verifier...
py -3 src\113_verify_akervatten_web_v0a.py --base-dist "%BASE%" --dist "%DIST%" --work "%WORK%"
if errorlevel 1 goto :fail

echo.
echo ========================================================================================
echo BUILD_AKERVATTEN_WEB_V0A: PASS
echo ========================================================================================
echo Local output: %DIST%\index.html
echo AkerNorm + AkerFro preserved; AkerVatten added as a separate grouped layer.
echo No combined water score. No legal verdict. No deployment performed.
echo Start locally with START_AKERPASS_LOCAL.bat.
exit /b 0

:fail
echo.
echo ========================================================================================
echo BUILD_AKERVATTEN_WEB_V0A: FAIL
echo ========================================================================================
echo No deployment was performed.
exit /b 1
