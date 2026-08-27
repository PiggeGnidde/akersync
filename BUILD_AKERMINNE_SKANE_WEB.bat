@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "LOGDIR=data\derived\akerminne_v1a\skane\logs"
set "LOG=%LOGDIR%\skane_web.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ==============================================================================
echo AkerMinne v1a - FULL SKANE WEB 33 municipalities
 echo ==============================================================================
echo Regression + sidecars + UI wiring + verification. No geometry is recomputed.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)
if not exist "dist\municipalities.json" (
  echo FEL: befintlig AkerPass dist saknas. Kopiera/byggregla frozen dist-bas forst.
  exit /b 1
)
if not exist "data\derived\akerminne_v1a\skane\skane_qa.md" (
  echo FEL: full Skane AkerMinne QA saknas. Kor full Skane batch forst.
  exit /b 1
)

py -3 src\66_verify_akerminne_skurup_regression.py > "%LOG%" 2>&1
if errorlevel 1 goto :fail

py -3 src\67_build_akerminne_skane_web.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

py -3 src\59_patch_akerpass_akerminne_ui.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\61_revise_akerminne_ui_copy.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\68_patch_akerpass_akerminne_skane_ui.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

py -3 src\43_verify_akerpass_web_v1.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\69_verify_akerminne_skane_web.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE FULL SKANE WEB: PASS
echo ==============================================================================
echo Regression:
echo   data\derived\akerminne_v1a\skane\skurup_regression.md
echo Web QA:
echo   data\derived\akerminne_v1a\skane\skane_web_qa.md
echo Starta sedan:
echo   CALL START_AKERPASS_LOCAL.bat
echo Oppna valfri kommun i Skane och klicka pa ett skifte.
exit /b 0

:fail
type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE FULL SKANE WEB: FAIL
echo ==============================================================================
echo Ingen historisk geometri har raknats om i detta steg.
echo Returnera loggen: %LOG%
exit /b 1
