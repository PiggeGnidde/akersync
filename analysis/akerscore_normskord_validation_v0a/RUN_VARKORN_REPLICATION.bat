@echo off
setlocal
chcp 65001 >nul

set "ROOT=C:\AkerSyncRepo"
set "INPUT=%ROOT%\work\akerscore_validation_csv_upload"
set "LOCALPATHS=%ROOT%\config\local_paths.json"
set "TAS=C:\AkerSyncRaw\smhi\SMHI_pthbv_tas_2011_2025_monthly.nc"
set "PR=C:\AkerSyncRaw\smhi\SMHI_pthbv_pr_2011_2025_monthly.nc"
set "OUT=%ROOT%\work\akerscore_normskord_varkorn_v0a"
set "HERE=%~dp0"
set "BASE=%HERE%run_varkorn_validation.py"
set "PREP=%HERE%prepare_pthbv_climate_varkorn.py"
set "MODEL=%HERE%run_climate_validation.py"
set "NORM=%HERE%normskord_varkorn_2026.csv"

where py >nul 2>nul
if errorlevel 1 (set "PY=python") else (set "PY=py -3")

if not exist "%TAS%" echo FAIL: missing %TAS% & exit /b 2
if not exist "%PR%" echo FAIL: missing %PR% & exit /b 2
if not exist "%INPUT%\field_static_context_selected.csv.gz" echo FAIL: missing frozen inputs & exit /b 2

if not exist "%OUT%" mkdir "%OUT%"

echo ====================================================================================
echo Varkorn independent replication: AkerScore + Normskord + PTHBV climate
 echo ====================================================================================
echo.
echo [1/4] Varkorn normskord bridge...
%PY% "%BASE%" --input-dir "%INPUT%" --output-dir "%OUT%\base" --norm-csv "%NORM%"
if errorlevel 1 goto :fail

echo.
echo [2/4] Varkorn-field weighted PTHBV climate...
%PY% "%PREP%" --temp-netcdf "%TAS%" --precip-netcdf "%PR%" --input-dir "%INPUT%" --local-paths "%LOCALPATHS%" --output-dir "%OUT%\climate"
if errorlevel 1 goto :fail

echo.
echo [3/4] All published Skane-domain SKO...
%PY% "%MODEL%" --sko-fit-table "%OUT%\base\sko_fit_table.csv" --climate-csv "%OUT%\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\all_sko"
if errorlevel 1 goto :fail

echo.
echo [4/4] Pre-specified geographic core: exclude cross-county SKO 0731 1124 1131 1321...
%PY% "%MODEL%" --sko-fit-table "%OUT%\base\sko_fit_table.csv" --climate-csv "%OUT%\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\geographic_core" --exclude-sko 0731 1124 1131 1321
if errorlevel 1 goto :fail

echo.
echo ====================================================================================
echo RUN_VARKORN_REPLICATION: PASS
echo ====================================================================================
echo Main results:
echo   %OUT%\base\results.json
echo   %OUT%\climate\sko_climate_2011_2025_apr_jul.csv
echo   %OUT%\all_sko\climate_results.json
echo   %OUT%\geographic_core\climate_results.json
exit /b 0

:fail
echo.
echo ====================================================================================
echo RUN_VARKORN_REPLICATION: FAIL
echo ====================================================================================
exit /b 1
