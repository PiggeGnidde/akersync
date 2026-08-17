@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Value Regression v0c · multi-block reconstruction
 echo ================================================================================
echo.
echo Valj ATL_AkerSync_2026-08-17_436_poster_v03.csv i filrutan.
echo.
echo v0c valjer block ENDAST fran lage + narhet + sald akerareal.
echo Geometri raknas forst efter att blockuppsattningen ar last.
echo.
py -3 src\20c_value_regression_v0c.py
if errorlevel 1 (
  echo.
  echo FEL: v0c avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output ligger i data\derived\value_regression_v0c\
echo Skicka report.txt, model_comparison.csv, multiblock_reconstruction.csv,
echo multiblock_members.csv och multiblock_geometry_sensitivity.csv till ChatGPT.
pause
