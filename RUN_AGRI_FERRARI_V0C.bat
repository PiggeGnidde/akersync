@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================================
echo ÅkerSync · skifte-Ferrari · klass 5-10 · v0c
echo ============================================================================================
echo.
echo Jord-only experiment:
echo   - score varje 2025-skifte i historisk klass 5-10
echo   - lar klass-10-signatur pa lera/silt + intern texturvariation
echo   - spatial 10 km holdout mot lokal leakage
echo   - hittar Ferrari-lika skiften utanfor klass 10
echo   - hittar icke-Ferrari-lika skiften inne i klass 10
echo.
py -3 src\30c_skifte_ferrari_v0c.py
if errorlevel 1 (
  echo.
  echo FEL: v0c avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\agri_class5_10_v0c_ferrari\
echo.
echo Skicka helst:
echo   report.txt
echo   ferrari_by_historic_class.csv
echo   ferrari_outside_class10.csv
echo   non_ferrari_inside_class10.csv
echo   skifte_ferrari_scores.csv
echo.
echo Oppna ferrari_anomaly_map.html for kartan.
pause
