@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0d · geography baseline sanity check
echo ================================================================================
echo.
echo Valj ATL_AkerSync_2026-08-17_436_poster_v03.csv i filrutan.
echo Forvantat huvudsample: 56 rena case fran 2020-07-01.
echo G1 LOO ska ligga runt 0.449810.
echo G2 ar kvadratisk geografi och jamfors utan jord/TWI i denna check.
echo.
py -3 src\20d_value_regression_v0d.py --baseline-only
pause
