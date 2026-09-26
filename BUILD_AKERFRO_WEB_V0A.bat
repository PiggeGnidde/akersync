@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if "%~1"=="" goto :usage
set "BASE=%~f1"
set "PRODUCT=C:\AkerSync-AkerFro\data\derived\akerfro_ertor_v0a\artkandidat_v0a_operational_fields.parquet"
if not "%~2"=="" set "PRODUCT=%~f2"
set "DIST=%~dp0dist"
if not "%~3"=="" set "DIST=%~f3"
set "WORK=%~dp0work\akerfro_web_v0a"

echo ========================================================================================
echo AkerFro - Ertor MVP v0a - LOCAL WEB BUILD ON AKERNORM BASE
echo ========================================================================================
echo AkerNorm base: %BASE%
echo Frozen product: %PRODUCT%
echo Target dist: %DIST%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before web build.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerfro-web-v0a" (
  echo FAIL: expected feature/akerfro-web-v0a, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)
py -3 -c "import pandas, pyarrow" >nul 2>nul
if errorlevel 1 (
  echo FAIL: pandas and pyarrow are required.
  exit /b 1
)
if not exist "%BASE%\index.html" (
  echo FAIL: AkerNorm base index.html missing.
  exit /b 1
)
if not exist "%BASE%\data\akernorm\skane_index.json" (
  echo FAIL: base dist does not contain AkerNorm sidecars.
  exit /b 1
)
if not exist "%PRODUCT%" (
  echo FAIL: frozen AkerFro operational product missing.
  exit /b 1
)
if not exist "C:\AkerSync-AkerFro\VERIFY_AKERFRO_OPERATIONAL_MVP_V0A_FREEZE.bat" (
  echo FAIL: AkerFro operational freeze verifier missing.
  exit /b 1
)

echo [1/4] Verify frozen AkerFro operational MVP...
CALL C:\AkerSync-AkerFro\VERIFY_AKERFRO_OPERATIONAL_MVP_V0A_FREEZE.bat
if errorlevel 1 goto :fail

echo.
echo [2/4] Web regression tests...
py -3 -m unittest tests.test_akerfro_web_v0a -v
if errorlevel 1 goto :fail

echo.
echo [3/4] Build municipality-lazy AkerFro sidecars + UI...
for /f "delims=" %%H in ('git rev-parse HEAD') do set "AKERFRO_WEB_REPOSITORY_HEAD=%%H"
py -3 src\88_build_akerfro_web_v0a.py --base-dist "%BASE%" --akerfro-product "%PRODUCT%" --dist "%DIST%" --work "%WORK%"
if errorlevel 1 goto :fail

echo.
echo [4/4] Independent web verifier...
py -3 src\90_verify_akerfro_web_v0a.py --base-dist "%BASE%" --dist "%DIST%" --work "%WORK%"
if errorlevel 1 goto :fail

echo.
echo ========================================================================================
echo BUILD_AKERFRO_WEB_V0A: PASS
echo ========================================================================================
echo Local output: %DIST%\index.html
echo AkerNorm preserved; AkerFro added as a separate lazy layer.
echo No deployment performed.
echo Start locally with START_AKERPASS_LOCAL.bat.
exit /b 0

:usage
echo Usage:
echo   BUILD_AKERFRO_WEB_V0A.bat "AKERNORM_BASE_DIST" ["AKERFRO_PRODUCT"] ["TARGET_DIST"]
echo.
echo Example:
echo   BUILD_AKERFRO_WEB_V0A.bat "C:\AkerSyncRepo\dist"
exit /b 2

:fail
echo.
echo ========================================================================================
echo BUILD_AKERFRO_WEB_V0A: FAIL
echo ========================================================================================
echo No deployment was performed.
exit /b 1
