@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0e · soil texture
echo ================================================================================
echo.
echo Valj ATL_AkerSync_2026-08-17_436_poster_v03.csv i filrutan.
echo.
echo v0e testar jordtextur och variation, inte geometri som prisvariabel.
echo Multi-block rekonstruktion anvands for transaction-level jord och kravs ±20%% areamatch.
echo Mull/organisk halt behandlas kategoriskt enligt DSMS-klasserna.
echo.
py -3 src\20e_value_regression_v0e.py
if errorlevel 1 (
  echo.
  echo FEL: v0e avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output ligger i data\derived\value_regression_v0e\
echo Skicka report.txt, soil_model_comparison.csv, soil_model_coefficients.csv,
echo soil_robustness_summary.csv och organic_class_summary.csv till ChatGPT.
pause
