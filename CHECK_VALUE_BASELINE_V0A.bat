@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================== 
echo ÅkerSync · Value Regression v0a · baseline sanity check
echo ============================================================================== 
echo.
echo Välj ATL_AkerSync_2026-08-17_315_poster_v03.csv.
echo För den filen väntar vi oss 32 rena case och LOO R2 cirka 0.512813.
echo.
py -3 src\20_value_regression_v0a.py --baseline-only
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
  echo FEL: baseline check avslutades med kod %RC%.
) else (
  echo Baseline check klar.
)
echo.
pause
exit /b %RC%
