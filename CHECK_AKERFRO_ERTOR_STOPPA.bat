@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - CHECK STOPPUNKT A
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 -m unittest tests.test_akerfro_cropcode_year_specific -v
if errorlevel 1 goto :fail

call RUN_AKERFRO_ERTOR_STOPPA.bat
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo CHECK STOPPUNKT A: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo CHECK STOPPUNKT A: FAIL
echo ==============================================================================
exit /b 1
