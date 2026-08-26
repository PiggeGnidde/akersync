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

type "%LOG%"
echo.
if exist "%REPORT%" (
  echo ==============================================================================
  type "%REPORT%"
  echo ==============================================================================
)

echo AKERMINNE OFFICIAL CROP CODES: PASS

if exist "dist\municipalities.json" goto :build_web

echo.
echo WEB PILOT: SKIPPED
 echo dist\municipalities.json saknas i denna rena clone.
echo Grodkoder och AkerMinne-QA ar klara; ingen geometri eller mapping har raknats om.
echo Bygg/kopiera en frozen AkerPass dist-bas separat innan UI-steget.
echo.
exit /b 0

:build_web
echo.
echo dist-bas hittad - bygger AkerMinne web pilot...
call BUILD_AKERMINNE_WEB_PILOT.bat
if errorlevel 1 goto :fail_web
echo.
echo AKERMINNE WEB PILOT: PASS
echo Starta sedan: CALL START_AKERPASS_LOCAL.bat
echo Oppna: http://localhost:8000/?kommun=Skurup
echo.
exit /b 0

:fail_web
echo.
echo ==============================================================================
echo AKERMINNE OFFICIAL CROP CODES: PASS, MEN WEB PILOT: FAIL
 echo ==============================================================================
echo Grodkodsrelabeln ar redan applicerad och verifierad.
exit /b 1

:fail
type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE OFFICIAL CROP CODES: FAIL
 echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
