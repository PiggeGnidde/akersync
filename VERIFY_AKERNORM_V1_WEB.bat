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
echo AkerNorm V1 - INDEPENDENT LOCAL WEB VERIFIER - STOPPUNKT D
echo ========================================================================================

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before STOPPUNKT D verification.
  git status --short
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 exit /b 1
py -3 -c "import pandas, pyarrow" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python packages pandas and pyarrow are required.
  exit /b 1
)
if not exist "%OUT%\manifests\akernorm_web_manifest.json" (
  echo FAIL: AkerNorm web PASS manifest is missing.
  exit /b 1
)
if not exist "%DIST%\data\akernorm\skane_index.json" (
  echo FAIL: AkerNorm web index is missing.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

py -3 src\87_verify_akernorm_v1_web.py --output-root "%OUT%" --base-dist "%BASE%" --dist "%DIST%" > "%OUT%\logs\stopd_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopd_verify.log"
if not "%RC%"=="0" goto :fail

echo.
echo VERIFY_AKERNORM_V1_WEB: PASS
echo STOPPUNKT D - do not tag, merge, deploy or touch Sentinel-2 without explicit GO.
echo.
echo Return:
echo   1. %OUT%\logs\web_tests.log
echo   2. %OUT%\logs\web_base_verify.log
echo   3. %OUT%\logs\web_build.log
echo   4. %OUT%\logs\stopd_verify.log
echo   5. %OUT%\manifests\akernorm_web_manifest.json
echo   6. %OUT%\qa\web_qa.md
echo   7. %OUT%\qa\web_payload_sizes.csv
echo   8. %OUT%\qa\stopd_verification.json
echo   9. %OUT%\qa\web_test_cases.json with direct local field URLs
echo  10. Screenshots: adjusted, official-only, unavailable, Kristianstad + 2 municipalities, mobile
echo  11. Every WARN, ERROR, FAIL, MISMATCH and BLOCKED line under %OUT%\logs
exit /b 0

:usage
echo Usage:
echo   VERIFY_AKERNORM_V1_WEB.bat "FROZEN_BASE_DIST" ["OUTPUT_ROOT"] ["TARGET_DIST"]
echo Example:
echo   VERIFY_AKERNORM_V1_WEB.bat "C:\AkerSync-Prestation\dist"
exit /b 2

:fail
echo.
echo VERIFY_AKERNORM_V1_WEB: FAIL
echo Return: %OUT%\logs\stopd_verify.log and any web_verify_traceback.log
exit /b 1
