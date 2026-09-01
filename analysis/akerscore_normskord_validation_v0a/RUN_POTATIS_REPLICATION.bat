@echo off
setlocal
chcp 65001 >nul

set "ROOT=C:\AkerSyncRepo"
set "INPUT=%ROOT%\work\akerscore_validation_csv_upload"
set "LOCALPATHS=%ROOT%\config\local_paths.json"
set "TAS=C:\AkerSyncRaw\smhi\SMHI_pthbv_tas_2011_2025_monthly.nc"
set "PR=C:\AkerSyncRaw\smhi\SMHI_pthbv_pr_2011_2025_monthly.nc"
set "OUT=%ROOT%\work\akerscore_normskord_potatis_v0a"
set "HERE=%~dp0"
set "FETCH=%HERE%fetch_normskord_crop_2026.py"
set "BASE=%HERE%run_specialcrop_validation.py"
set "PREP=%HERE%prepare_pthbv_climate_specialcrop.py"
set "MODEL=%HERE%run_climate_validation_optional.py"

where py >nul 2>nul
if errorlevel 1 (set "PY=python") else (set "PY=py -3")

if not exist "%TAS%" (
  echo FAIL: missing %TAS%
  exit /b 2
)
if not exist "%PR%" (
  echo FAIL: missing %PR%
  exit /b 2
)
if not exist "%INPUT%\field_static_context_selected.csv.gz" (
  echo FAIL: missing frozen inputs
  exit /b 2
)
if not exist "%LOCALPATHS%" (
  echo FAIL: missing %LOCALPATHS%
  exit /b 2
)
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OUT%\matpotatis" mkdir "%OUT%\matpotatis"
if not exist "%OUT%\starkelsepotatis" mkdir "%OUT%\starkelsepotatis"

echo ====================================================================================
echo Potatis replication: Matpotatis + Starkelsepotatis
echo ====================================================================================

echo.
echo [1/10] Fetch Matpotatis 2026 normskord...
%PY% "%FETCH%" --crop "Matpotatis" --output "%OUT%\matpotatis\normskord_2026.csv"
if errorlevel 1 goto :fail

echo.
echo [2/10] Matpotatis score-only bridge...
%PY% "%BASE%" --input-dir "%INPUT%" --output-dir "%OUT%\matpotatis\base" --norm-csv "%OUT%\matpotatis\normskord_2026.csv" --crop-code 45 --crop-label "Matpotatis" --label-pattern "potatis" --min-sko 4
if errorlevel 1 goto :fail

echo.
echo [3/10] Matpotatis field-weighted PTHBV climate...
%PY% "%PREP%" --temp-netcdf "%TAS%" --precip-netcdf "%PR%" --input-dir "%INPUT%" --local-paths "%LOCALPATHS%" --output-dir "%OUT%\matpotatis\climate" --crop-code 45 --crop-label "Matpotatis" --label-pattern "potatis"
if errorlevel 1 goto :fail

echo.
echo [4/10] Matpotatis climate model if n permits...
%PY% "%MODEL%" --sko-fit-table "%OUT%\matpotatis\base\sko_fit_table.csv" --climate-csv "%OUT%\matpotatis\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\matpotatis\all_sko" --label "Matpotatis"
if errorlevel 1 goto :fail

echo.
echo [5/10] Matpotatis geographic core climate if n permits...
%PY% "%MODEL%" --sko-fit-table "%OUT%\matpotatis\base\sko_fit_table.csv" --climate-csv "%OUT%\matpotatis\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\matpotatis\geographic_core" --exclude-sko 0731 1124 1131 1321 --label "Matpotatis core"
if errorlevel 1 goto :fail

echo.
echo [6/10] Fetch Potatis for starkelse 2026 normskord...
%PY% "%FETCH%" --crop "Potatis för stärkelse" --output "%OUT%\starkelsepotatis\normskord_2026.csv"
if errorlevel 1 goto :fail

echo.
echo [7/10] Starkelsepotatis score-only bridge...
%PY% "%BASE%" --input-dir "%INPUT%" --output-dir "%OUT%\starkelsepotatis\base" --norm-csv "%OUT%\starkelsepotatis\normskord_2026.csv" --crop-code 46 --crop-label "Stärkelsepotatis" --label-pattern "potatis" --min-sko 4
if errorlevel 1 goto :fail

echo.
echo [8/10] Starkelsepotatis field-weighted PTHBV climate...
%PY% "%PREP%" --temp-netcdf "%TAS%" --precip-netcdf "%PR%" --input-dir "%INPUT%" --local-paths "%LOCALPATHS%" --output-dir "%OUT%\starkelsepotatis\climate" --crop-code 46 --crop-label "Stärkelsepotatis" --label-pattern "potatis"
if errorlevel 1 goto :fail

echo.
echo [9/10] Starkelsepotatis climate model if n permits...
%PY% "%MODEL%" --sko-fit-table "%OUT%\starkelsepotatis\base\sko_fit_table.csv" --climate-csv "%OUT%\starkelsepotatis\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\starkelsepotatis\all_sko" --label "Stärkelsepotatis"
if errorlevel 1 goto :fail

echo.
echo [10/10] Starkelsepotatis geographic core climate if n permits...
%PY% "%MODEL%" --sko-fit-table "%OUT%\starkelsepotatis\base\sko_fit_table.csv" --climate-csv "%OUT%\starkelsepotatis\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\starkelsepotatis\geographic_core" --exclude-sko 0731 1124 1131 1321 --label "Stärkelsepotatis core"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================
echo RUN_POTATIS_REPLICATION: PASS
echo ====================================================================================
echo Main results under:
echo   %OUT%\matpotatis
echo   %OUT%\starkelsepotatis
echo Climate models are automatically skipped when fewer than 8 complete SKO remain.
exit /b 0

:fail
echo.
echo ====================================================================================
echo RUN_POTATIS_REPLICATION: FAIL
echo ====================================================================================
exit /b 1
