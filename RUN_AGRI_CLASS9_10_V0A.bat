@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Jordbruksklass 9/10 · jordprofil v0a
echo ================================================================================
echo.
echo Hamtar digitala klass 9/10-polygoner och lagger dem mot DSMS2025.
echo Kommuner ar INTE urvalsenhet; klasspolygonernas 20x20 m-pixlar raknas areaviktat.
echo.
echo A = hela historiska klassytan.
echo B = den del som fortfarande ligger i 2025 jordbruksblock.
echo.
py -3 src\30_agri_class9_10_v0a.py
if errorlevel 1 (
  echo.
  echo FEL: klass 9/10-analysen avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\agri_class9_10_v0a\
echo Skicka report.txt, class9_10_soil_summary.csv,
echo class9_10_texture_covariance.csv och class9_10_organic_summary.csv till ChatGPT.
pause
