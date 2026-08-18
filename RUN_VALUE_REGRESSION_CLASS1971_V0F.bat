@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0f · 1971 jordbruksklass mot pris
echo ================================================================================
echo.
echo Huvudtest:
echo   log(pris/aker-ha) mot historisk klass 1-10,
echo   jamfort med ar+area och geografimodeller G1/G2.
echo.
echo Transaktionsklass raknas areaviktat over v0c-rekonstruerade block.
echo Main sample krav: +/-20%% areamatch och >=80%% klasskartetackning.
echo.
py -3 src\20f_value_regression_class1971_v0f_runner.py
if errorlevel 1 (
  echo.
  echo FEL: v0f avbrot. Kopiera hela feltexten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART.
echo Output: data\derived\value_regression_v0f_class1971\
echo.
echo Skicka helst:
echo   report.txt
echo   class1971_model_comparison.csv
echo   class1971_incremental_tests.csv
echo   class1971_model_coefficients.csv
echo   observed_price_by_class1971.csv
echo   class1971_pricing_residual_candidates.csv
pause
