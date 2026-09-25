@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - C6 ARTMATCH CANDIDATE SCORE
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 -m unittest tests.test_akerfro_build_artmatch_c6 -v
if errorlevel 1 goto :fail

py -3 analysis\akerfro_ertor_v0a\build_artmatch_c6.py
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo ==============================================================================
echo C6 ARTMATCH CANDIDATE SCORE: FAIL
echo ==============================================================================
exit /b 1
