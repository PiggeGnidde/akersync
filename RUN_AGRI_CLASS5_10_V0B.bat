@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Jordbruksklass 5-10 · jordprofil v0b
echo ================================================================================
echo.
echo Hamtar digitala klass 5-10-polygoner och lagger dem mot DSMS2025.
echo Kommuner ar INTE urvalsenhet; klasspolygonernas 20x20 m-pixlar raknas areaviktat.
echo.
echo A = hela historiska klassytan.
echo B = den del som fortfarande ligger i 2025 jordbruksblock.
echo.
py -3 src\30b_agri_class5plus_v0b.py
if errorlevel 1 (
  echo.
  echo FEL: klass 5-10-analysen avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\agri_class5_10_v0b\
echo Skicka report.txt, class5_10_soil_summary.csv,
echo class5_10_texture_covariance.csv, class5_10_organic_summary.csv
echo och class5_10_gradient_current_farmland.csv till ChatGPT.
pause
