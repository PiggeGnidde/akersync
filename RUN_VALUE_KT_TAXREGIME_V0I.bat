@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0i · K/T taxeringsregimer
echo ================================================================================
echo.
echo Ateranvander LOCKED v0h-output. Ingen ny GIS/DSMS-korning.
echo Jämfor linjart ar mot taxeringsregimer 2020-22 / 2023-25 / 2026+
echo samt gemensam trend inom taxeringsregim.
echo.
echo Testar ocksa Ferrari-surprise relativt beskaffenhet + geografi.
echo.
py -3 src\20i_value_kt_taxregime_v0i.py
if errorlevel 1 (
  echo.
  echo FEL: v0i avbrot. Kopiera hela feltexten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART.
echo Output: data\derived\value_regression_v0i_kt_taxregime\
echo.
echo Skicka helst:
echo   report.txt
echo   tax_regime_summary.csv
echo   kt_regime_model_comparison.csv
echo   kt_regime_incremental_tests.csv
echo   kt_regime_model_coefficients.csv
echo   soil_surprise_besk_geo_model.csv
pause
