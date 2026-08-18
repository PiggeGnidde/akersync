@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · extrema Ferrari-anomalier · v0d
echo ================================================================================
echo.
echo Detta steg ateranvander v0c-scorefilen och gor ett striktare anomalitest:
echo   Super-Ferrari utanfor klass 10 = FerrariScore >= klass-10 OOF P90
echo   Extrem icke-Ferrari inne i klass 10 = FerrariScore <= klass-10 OOF P05
echo.
echo Dessutom beraknas avstand fran varje Super-Ferrari till narmaste
 echo historiska klass-10-polygon och en ny HTML-karta byggs.
echo.
if not exist data\derived\agri_class5_10_v0c_ferrari\skifte_ferrari_scores.csv (
  echo FEL: v0c scorefil saknas.
  echo Kor RUN_AGRI_FERRARI_V0C.bat forst.
  pause
  exit /b 1
)
py -3 src\30d_ferrari_extremes_v0d.py
if errorlevel 1 (
  echo.
  echo FEL: v0d avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\agri_class5_10_v0d_extremes\
echo Oppna ferrari_extreme_anomaly_map.html for kartan.
echo Skicka report.txt samt CSV-filerna till ChatGPT.
pause
