@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0d · geography robustness
echo ================================================================================
echo.
echo Valj ATL_AkerSync_2026-08-17_436_poster_v03.csv i filrutan.
echo.
echo v0d jamfor linjar lat/lon-geografi mot en modest kvadratisk geografi,
echo och testar om lera/TWI fortfarande ger CV-vinst ovanpa bada.
echo.
py -3 src\20d_value_regression_v0d.py
if errorlevel 1 (
  echo.
  echo FEL: v0d avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output ligger i data\derived\value_regression_v0d\
echo Skicka report.txt, geography_baseline_comparison.csv,
echo physics_model_comparison.csv och robustness_summary.csv till ChatGPT.
pause
