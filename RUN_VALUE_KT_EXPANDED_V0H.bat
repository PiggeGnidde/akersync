@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0h · expanded K/T sample
echo ================================================================================
echo.
echo Target: log(kopeskilling / totalt taxeringsvarde)
echo Tillater bebyggda och delvis blandade lantbruksfastigheter.
echo Beskaffenhet = fastighetstaxeringens produktions-/brukningsklass, INTE jordprov.
echo Modern Ferrari-jord laggs pa dar blockrekonstruktionen klarar QA.
echo.
py -3 src\20h_value_kt_expanded_v0h_runner.py
if errorlevel 1 (
  echo.
  echo FEL: v0h avbrot. Kopiera hela feltexten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART.
echo Output: data\derived\value_regression_v0h_kt_expanded\
echo.
echo Skicka helst:
echo   report.txt
echo   sample_counts.csv
echo   kt_model_comparison.csv
echo   kt_incremental_tests.csv
echo   kt_model_coefficients.csv
echo   beskaffenhet_summary.csv
echo   drainage_summary.csv
echo.
pause
