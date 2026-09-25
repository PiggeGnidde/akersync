@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor MVP v0a - C3 MATCHED PU RANKING
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 -m unittest tests.test_akerfro_matched_ranking_c3 -v
if errorlevel 1 goto :fail

py -3 analysis\akerfro_ertor_v0a\matched_ranking_c3.py
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo ==============================================================================
echo C3 MATCHED PU RANKING: FAIL
echo ==============================================================================
exit /b 1
