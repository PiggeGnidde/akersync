@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if "%~1"=="" goto :usage
set "BASE=%~f1"
set "OUT=%~dp0data\derived\akernorm_v1"
if not "%~2"=="" set "OUT=%~f2"
set "DIST=%~dp0dist"
if not "%~3"=="" set "DIST=%~f3"

echo ========================================================================================
echo AkerNorm V1 - LOCAL WEB BUILD - STOPPUNKT D
echo ========================================================================================
echo Frozen base web: %BASE%
echo STOPPUNKT C:     %OUT%
echo Local output:    %DIST%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before web build.
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
py -3 -c "import pandas, pyarrow" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python packages pandas and pyarrow are required.
  exit /b 1
)
if not exist "%BASE%\index.html" (
  echo FAIL: frozen base dist/index.html is missing.
  exit /b 1
)
if not exist "%BASE%\data\akerminne\skane_index.json" (
  echo FAIL: frozen base ÅkerMinne all-Skåne sidecars are missing.
  exit /b 1
)
if not exist "%OUT%\manifests\full_skane_manifest.json" (
  echo FAIL: STOPPUNKT C full manifest is missing.
  exit /b 1
)
if not exist "%OUT%\qa\stopc_verification.json" (
  echo FAIL: independent STOPPUNKT C verification is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

echo [1/3] AkerNorm web regression tests...
py -3 -m unittest discover -s tests -p "test_akernorm_v1_web.py" -v > "%OUT%\logs\web_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\web_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/3] Verify frozen Score/Value/Drift/Minne base web...
py -3 src\69b_verify_akerpass_akerminne_phase0_combined.py --dist "%BASE%" > "%OUT%\logs\web_base_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\web_base_verify.log"
if not "%RC%"=="0" goto :fail

echo.
echo [3/3] Build separate municipality-lazy AkerNorm data and local UI...
for /f "delims=" %%H in ('git rev-parse HEAD') do set "AKERNORM_REPOSITORY_HEAD=%%H"
py -3 src\85_build_akernorm_v1_web.py --output-root "%OUT%" --base-dist "%BASE%" --dist "%DIST%" > "%OUT%\logs\web_build.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\web_build.log"
if not "%RC%"=="0" goto :fail

echo.
echo BUILD_AKERNORM_V1_WEB: PASS
echo Local file: %DIST%\index.html
echo Start locally with START_AKERPASS_LOCAL.bat.
echo No deployment, tag, merge or Sentinel-2 work ran.
echo Run VERIFY_AKERNORM_V1_WEB.bat next.
exit /b 0

:usage
echo Usage:
echo   BUILD_AKERNORM_V1_WEB.bat "FROZEN_BASE_DIST" ["OUTPUT_ROOT"] ["TARGET_DIST"]
echo Example:
echo   BUILD_AKERNORM_V1_WEB.bat "C:\AkerSync-Prestation\dist"
exit /b 2

:fail
echo.
echo BUILD_AKERNORM_V1_WEB: FAIL
echo Return: %OUT%\logs\web_tests.log, web_base_verify.log, web_build.log and any *_traceback.log
exit /b 1
