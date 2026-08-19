@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync / ÅkerScore · jordfyrtupel v0b
echo ================================================================================
echo.
echo v0b återanvänder training_sample.csv.gz från v0a.
echo Den gör 10x10 km spatial CV och kalibrerar display-skalan till
echo klasscentrum 45,55,65,75,85,95 utan att mata in historisk klass vid scoring.
echo.
if not exist "data\derived\akerscore_soil_v0a\training_sample.csv.gz" (
  echo Saknar v0a training sample. Kör RUN_AKERSCORE_SOIL_V0A.bat först.
  pause
  exit /b 1
)
py -3 src\31b_akerscore_soil_v0b.py
if errorlevel 1 (
  echo.
  echo FEL: ÅkerScore soil v0b avbröts. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\akerscore_soil_v0b\
echo Skicka:
echo   report.txt
echo   spatial_cv_class_summary_raw.csv
echo   spatial_cv_class_summary_calibrated.csv
echo   german_triesdorf_reference_scores_v0b.csv
echo.
pause
