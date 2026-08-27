@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ==============================================================================
echo AkerMinne v1a - Skurup pilot vs Skane regression
echo ==============================================================================

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 src\66_verify_akerminne_skurup_regression.py
if errorlevel 1 exit /b 1

echo.
echo AKERMINNE SKURUP REGRESSION: PASS
exit /b 0
