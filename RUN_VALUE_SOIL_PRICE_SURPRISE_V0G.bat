@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0g · modern jord-surprise mot marknadspris
echo ================================================================================
echo.
echo Forutsattning:
echo   RUN_VALUE_REGRESSION_CLASS1971_V0F.bat skall ha kort klart.
echo   Agri-class v0c skifte_ferrari_scores.csv skall finnas i C:\AkerSyncClass910.
echo.
echo v0g ateranvander exakt samma rekonstruerade affarer som v0f.
echo Ingen ny blockselektion gors.
echo.
py -3 src\20g_value_soil_price_surprise_v0g.py
if errorlevel 1 (
  echo.
  echo FEL: v0g avbrot. Kopiera hela feltexten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART.
echo Output: data\derived\value_regression_v0g_soil_price_surprise\
echo.
echo Skicka helst:
echo   report.txt
echo   price_model_comparison.csv
echo   price_incremental_soil_tests.csv
echo   soil_surprise_models.csv
echo   soil_price_correlations.csv
echo   pricing_soil_candidate_ranking.csv
echo.
pause
