@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================================================
echo AkerPass MVP UI V1 - public data, 33 kommuner, mobil karta och QA
echo ========================================================================================
echo.

if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas.
  echo Kor SETUP_PATHS.bat eller kopiera config\local_paths.example.json och fyll i sokvagarna.
  pause
  exit /b 1
)

if not exist "data\derived\geometry_payload.json" (
  echo FEL: geometry_payload.json saknas. Kor BUILD_ALL.bat eller ditt befintliga Skane-databygge forst.
  pause
  exit /b 1
)

if not exist "data\derived\geometry_v1a_skiften.csv" (
  echo Geometry V1a saknas. Bygger den nu...
  py -3 src\09_geometry_v1a.py
  if errorlevel 1 python src\09_geometry_v1a.py
  if errorlevel 1 goto :error
)

if not exist "data\derived\akerscore_soil_v0c\akerscore_soil_skiften.csv" (
  echo FEL: fryst AkerScore v0c-output saknas.
  echo Kor RUN_AKERSCORE_SOIL_V0C.bat forst.
  pause
  exit /b 1
)

if not exist "data\derived\akervarde_v1_0_rc1_freeze\model_coefficients.csv" (
  echo FEL: fryst AkerVarde-artifact saknas.
  echo Kor FREEZE_AKERVARDE_V1RC.bat forst.
  pause
  exit /b 1
)

py -3 src\build_akerpass_web_v1.py
if errorlevel 1 python src\build_akerpass_web_v1.py
if errorlevel 1 goto :error

echo.
echo KLART: dist\index.html
echo Starta lokal verifiering med START_AKERPASS_LOCAL.bat
echo.
pause
exit /b 0

:error
echo.
echo FEL: AkerPass-bygget avbrots. Kopiera hela texten till kodchatten.
pause
exit /b 1

