@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=C:\AkerSyncRepo\work\akernorm_v1_discovery_stopA"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerNorm V1 - VERIFY DISCOVERY/REPRODUCTION - STOPPUNKT A
echo ========================================================================================

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before verification.
  git status --short
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)

if not exist "%OUT%\logs" mkdir "%OUT%\logs"
py -3 src\79_verify_akernorm_v1_reproduction.py --output-dir "%OUT%" > "%OUT%\logs\reproduction_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\reproduction_verify.log"
if not "%RC%"=="0" goto :fail

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: verifier changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo VERIFY_AKERNORM_V1_REPRODUCTION: PASS
echo STOPPUNKT A - do not continue without explicit GO MODELLFREEZE.
exit /b 0

:fail
echo.
echo VERIFY_AKERNORM_V1_REPRODUCTION: FAIL
echo Return: %OUT%\logs\reproduction_verify.log
exit /b 1
