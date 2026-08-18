@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync / ÅkerScore · jordfyrtupel v0a
echo ================================================================================
echo.
echo Modell: sand + silt + lera + mullproxy ^> kontinuerlig ÅkerScore.
echo Historisk klass 5-10 används ENDAST som tränings-/referenssignal.
echo Tysk Triesdorf-skörd används ENDAST som extern kontroll efter fit.
echo.
echo Förkrav: RUN_AGRI_CLASS5_10_V0B.bat ska ha körts minst en gång.
echo.
py -3 src\31_akerscore_soil_v0a.py
if errorlevel 1 (
  echo.
  echo FEL: ÅkerScore soil v0a avbröts. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\akerscore_soil_v0a\
echo Skicka i första hand dessa filer till ChatGPT:
echo   report.txt
echo   class_soil4_signature.csv
echo   training_class_score_summary.csv
echo   german_triesdorf_reference_scores.csv
echo.
pause
