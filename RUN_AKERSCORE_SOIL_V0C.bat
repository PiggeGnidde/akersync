@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync / ÅkerScore · soil v0c · tail scale + skiftevariation
echo ================================================================================
echo.
echo Behaller raw soil-signal oforandrad fran v0a/v0b.
echo Ny display-skala: klassmedianer 45..95, klass-10-svans 98..100.
echo Scorear sedan varje skifte pixel-for-pixel och rapporterar P10/P50/P90.
echo OBS: P10-P90 ar spatial variation inom akern, INTE konfidensintervall.
echo.
if not exist "data\derived\akerscore_soil_v0a\training_sample.csv.gz" (
  echo Forsta ÅkerScore-underlaget saknas. Kor RUN_AKERSCORE_SOIL_V0A.bat forst.
  pause
  exit /b 1
)
py -3 src\31c_akerscore_soil_v0c.py
if errorlevel 1 (
  echo.
  echo FEL: ÅkerScore soil v0c avbrots. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\akerscore_soil_v0c\
echo Skicka i forsta hand:
echo   report.txt
echo   tail_calibration_knots.csv
echo   german_triesdorf_reference_scores_v0c.csv
echo   skifte_class_score_summary.csv
echo   akerscore_soil_skiften.csv
echo.
pause
