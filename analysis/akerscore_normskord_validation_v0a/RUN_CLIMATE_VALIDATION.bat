@echo off
setlocal
chcp 65001 >nul

set "ROOT=C:\AkerSyncRepo"
set "INPUT=%ROOT%\work\akerscore_validation_csv_upload"
set "LOCALPATHS=%ROOT%\config\local_paths.json"
set "BASEFIT=%ROOT%\work\akerscore_normskord_validation_v0a\sko_fit_table.csv"
set "OUT=%ROOT%\work\akerscore_normskord_climate_v0a"
set "PTHBV=C:\AkerSyncRaw\smhi\pthbv_2011_2025_monthly.nc"
if not "%~1"=="" set "PTHBV=%~1"

set "HERE=%~dp0"
set "PREP=%HERE%prepare_pthbv_climate.py"
set "MODEL=%HERE%run_climate_validation.py"
set "REQ=%HERE%climate_requirements.txt"

echo ====================================================================================
echo AkerScore x Normskord x SMHI PTHBV climate validation v0a
echo ====================================================================================
echo PTHBV: %PTHBV%
echo.

if not exist "%PTHBV%" (
  echo FAIL: PTHBV NetCDF not found.
  echo.
  echo Download from SMHI PTHBV as:
  echo   Hela Sverige - NetCDF
  echo   2011 through 2025
  echo   Manadsvarden
  echo   Nederbord och temperatur
  echo.
  echo Save/rename it to:
  echo   C:\AkerSyncRaw\smhi\pthbv_2011_2025_monthly.nc
  echo.
  echo Or pass the downloaded file as first argument to this BAT file.
  exit /b 2
)

if not exist "%LOCALPATHS%" (
  echo FAIL: local paths config missing: %LOCALPATHS%
  exit /b 2
)
if not exist "%INPUT%\field_static_context_selected.csv.gz" (
  echo FAIL: frozen validation input missing: %INPUT%
  exit /b 2
)
if not exist "%BASEFIT%" (
  echo Base normskord fit is missing; running primary validation first...
  call "%HERE%RUN_VALIDATION.bat"
  if errorlevel 1 goto :fail
)

where py >nul 2>nul
if errorlevel 1 (
  set "PY=python"
) else (
  set "PY=py -3"
)

%PY% -c "import xarray, netCDF4" >nul 2>nul
if errorlevel 1 (
  echo Installing analysis-only NetCDF dependencies...
  %PY% -m pip install -r "%REQ%"
  if errorlevel 1 goto :fail
)

if not exist "%OUT%" mkdir "%OUT%"

echo.
echo [1/3] Exact PTHBV grid x wheat-field polygon overlay...
%PY% "%PREP%" --netcdf "%PTHBV%" --input-dir "%INPUT%" --local-paths "%LOCALPATHS%" --output-dir "%OUT%\climate"
if errorlevel 1 (
  echo.
  echo PTHBV parser/overlay failed. Printing NetCDF structure for diagnosis:
  %PY% "%HERE%inspect_pthbv.py" "%PTHBV%"
  goto :fail
)

echo.
echo [2/3] Score + climate model, all published SKO...
%PY% "%MODEL%" --sko-fit-table "%BASEFIT%" --climate-csv "%OUT%\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\all_sko"
if errorlevel 1 goto :fail

echo.
echo [3/3] Same climate model excluding 1321, 1124, 1221...
%PY% "%MODEL%" --sko-fit-table "%BASEFIT%" --climate-csv "%OUT%\climate\sko_climate_2011_2025_apr_jul.csv" --output-dir "%OUT%\excl_sparse" --exclude-sko 1321 1124 1221
if errorlevel 1 goto :fail

echo.
echo ====================================================================================
echo RUN_CLIMATE_VALIDATION: PASS
echo ====================================================================================
echo Main results:
echo   %OUT%\climate\sko_climate_2011_2025_apr_jul.csv
echo   %OUT%\all_sko\climate_results.json
echo   %OUT%\all_sko\sko_climate_model_table.csv
echo   %OUT%\excl_sparse\climate_results.json
exit /b 0

:fail
echo.
echo ====================================================================================
echo RUN_CLIMATE_VALIDATION: FAIL
echo ====================================================================================
exit /b 1
