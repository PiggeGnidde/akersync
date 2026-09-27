@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT B2 NADIA VALIDATION
echo ====================================================================================================

if "%~1"=="" (
  echo.
  echo Usage:
  echo   CALL RUN_AKERVATTEN_B2_NADIA_VALIDATE.bat "C:\path\to\downloaded_nadia_file.xls"
  exit /b 1
)

py -3 -c "import pandas,xlrd"
if errorlevel 1 (
  echo FAIL: pandas/xlrd missing.
  exit /b 1
)

py -3 src\95_akervatten_b2_nadia_validate.py "%~1"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_B2_NADIA_VALIDATE: PASS
echo ====================================================================================================
echo If this PASS is accepted, STOPPUNKT B can be frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_B2_NADIA_VALIDATE: FAIL
echo ====================================================================================================
exit /b 1
