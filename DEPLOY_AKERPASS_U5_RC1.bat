@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerpass-unified-u5-deploy" (
  echo FAIL: expected feature/akerpass-unified-u5-deploy, got %BRANCH%.
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
  echo FAIL: U5 deploy environment is not initialized.
  echo Run CALL SETUP_AKERPASS_U5_ONECOM.bat first.
  exit /b 1
)
"%PY%" -c "import paramiko" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Paramiko missing. Run setup first.
  exit /b 1
)

echo ====================================================================================================
echo ÅkerPass U5 - DEPLOY EXACT RC1 TO preview.akerpass.se
echo ====================================================================================================
echo Hard guards: pinned host key, confirmed preview root, existing .htaccess + .htpasswd, fixed RC1 SHA.
echo Existing preview is retained as a deny-all rollback snapshot until U6.
echo.

"%PY%" src\131_deploy_akerpass_u5_onecom.py
exit /b %ERRORLEVEL%
