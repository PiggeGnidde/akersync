@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - STOPPUNKT B
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 analysis\akerfro_ertor_v0a\build_history.py --akerminne-root C:\AkerSync-Minne
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo ==============================================================================
echo STOPPUNKT B: FAIL
echo ==============================================================================
exit /b 1
