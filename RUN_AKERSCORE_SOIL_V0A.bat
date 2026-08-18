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

set "CLASS_GPKG=data\derived\agri_class5_10_v0b\source\jord_skogsklassificering_class5_10.gpkg"
set "CLASS_SUMMARY=data\derived\agri_class5_10_v0b\class5_10_soil_summary.csv"

if not exist "%CLASS_GPKG%" goto build_prereq
if not exist "%CLASS_SUMMARY%" goto build_prereq
goto run_score

:build_prereq
echo Fördata från klass 5-10 saknas lokalt.
echo Bygger därför agri_class5_10_v0b automatiskt först...
echo.
py -3 src\30b_agri_class5plus_v0b.py
if errorlevel 1 (
  echo.
  echo FEL: automatisk klass 5-10-förkörning avbröts.
  echo Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo Klass 5-10-fördata klar.
echo.

:run_score
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
