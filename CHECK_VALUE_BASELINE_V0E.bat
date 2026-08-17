@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0e · baseline sanity check
echo ================================================================================
echo.
echo Valj ATL_AkerSync_2026-08-17_436_poster_v03.csv i filrutan.
echo Forvantat huvudsample: 56 rena case fran 2020-07-01.
echo G1 LOO R2 ska ligga runt 0.449810.
echo G2 LOO R2 ska ligga runt 0.450049.
echo.
py -3 src\20e_value_regression_v0e.py --baseline-only
if errorlevel 1 (
  echo.
  echo FEL: v0e baseline avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
pause
