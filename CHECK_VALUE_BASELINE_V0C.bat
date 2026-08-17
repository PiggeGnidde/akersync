@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0c · baseline sanity check
echo ================================================================================
echo.
echo Valj ATL_AkerSync_2026-08-17_436_poster_v03.csv i filrutan.
echo Forvantat huvudsample: 56 rena case fran 2020-07-01.
echo Baseline ska ligga runt LOO R2 = 0.449810.
echo.
py -3 src\20c_value_regression_v0c.py --baseline-only
pause
