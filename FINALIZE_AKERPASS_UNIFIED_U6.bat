@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerpass-unified-u6-freeze" (
  echo FAIL: expected feature/akerpass-unified-u6-freeze, got %BRANCH%.
  exit /b 1
)

git diff --quiet
if errorlevel 1 (
  echo FAIL: tracked working tree changes present.
  git status --short
  exit /b 1
)

set "PY=.venv\akerpass_u5\Scripts\python.exe"
if not exist "%PY%" (
  echo FAIL: U5/U6 deploy environment missing.
  echo Run CALL SETUP_AKERPASS_U5_ONECOM.bat if needed.
  exit /b 1
)

echo ====================================================================================================
echo ÅkerPass Unified Preview - U6 FINAL WEB FREEZE
echo ====================================================================================================
echo Input ACK: real mobile + Tesla browser; GPS / Följ mig / zoom across layers PASS.
echo This step performs NO rebuild and NO new deployment.
echo It removes only the exact guarded U5 rollback snapshot after final live verification.
echo.

"%PY%" src\133_finalize_akerpass_u6_freeze.py
if errorlevel 1 goto :fail

"%PY%" src\134_verify_akerpass_u6_freeze.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo AKERPASS UNIFIED PREVIEW U6: FINAL FREEZE / VERIFY PASS
echo ====================================================================================================
echo Hosted release: https://preview.akerpass.se/
echo Frozen artifact: akerpass-unified-preview-v0a-r1-rc1
echo SHA256: 01a96dda7ced90be99a686f8de081ed72fc19f0fd4b1adf556d42de7def48173
echo Future web-byte changes require a new release/version.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo AKERPASS UNIFIED PREVIEW U6: FAIL
echo ====================================================================================================
echo Do not call the hosted web frozen until the failing guard is resolved.
exit /b 1
