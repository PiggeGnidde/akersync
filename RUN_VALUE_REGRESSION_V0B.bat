@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================
echo AkerSync Value Regression v0b - 6 ar + blockarea-QA
echo ============================================================================
echo.
py -3 src\20b_value_regression_v0b.py
if errorlevel 1 (
  echo.
  echo KORNINGEN MISSLYCKADES. Skicka hela texten till ChatGPT.
) else (
  echo.
  echo KLART. Skicka report.txt, model_comparison.csv och geometry_area_match_sensitivity.csv.
)
pause
