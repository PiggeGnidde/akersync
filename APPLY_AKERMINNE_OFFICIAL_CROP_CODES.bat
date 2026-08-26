@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_official_crop_codes.log"
set "REPORT=data\derived\akerminne_v1a\crop_codes_official\official_crop_code_report.md"

echo ==============================================================================
echo AkerMinne v1a - official annual crop codes 2015-2025
echo ==============================================================================
echo Label-only update: geometry, overlap, coverage and identity matching are frozen.
echo.

if not exist "data\reference\akerminne_crop_codes_official\manifest.json" (
  echo FEL: official crop-code manifest saknas.
  exit /b 1
)
if not exist "data\derived\akerminne_v1a\pilot_skurup\akerminne_components.parquet" (
  echo FEL: AkerMinne pilot components saknas.
  exit /b 1
)
if not exist "data\derived\akerminne_v1a\pilot_skurup\akerminne_year_summary.parquet" (
  echo FEL: AkerMinne pilot summary saknas.
  exit /b 1
)
if not exist "dist\municipalities.json" (
  echo FEL: dist\municipalities.json saknas. Kor CALL BUILD_AKERPASS_WEB_V1.bat forst.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 src\60_apply_akerminne_official_crop_codes.py > "%LOG%" 2>&1
if errorlevel 1 goto :fail

call VERIFY_AKERMINNE_PILOT_SKURUP.bat >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

call BUILD_AKERMINNE_WEB_PILOT.bat >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

type "%LOG%"
echo.
if exist "%REPORT%" (
  echo ==============================================================================
  type "%REPORT%"
  echo ==============================================================================
)
echo AKERMINNE OFFICIAL CROP CODES: PASS
echo Starta sedan: CALL START_AKERPASS_LOCAL.bat
echo Oppna: http://localhost:8000/?kommun=Skurup
echo.
exit /b 0

:fail
type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE OFFICIAL CROP CODES: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
