@echo off
setlocal
chcp 65001 >nul

set "ROOT=C:\AkerSyncRepo"
set "INPUT=%ROOT%\work\akerscore_validation_csv_upload"
set "LOCALPATHS=%ROOT%\config\local_paths.json"
set "BASEFIT=%ROOT%\work\akerscore_normskord_validation_v0a\sko_fit_table.csv"
set "OUT=%ROOT%\work\akerscore_normskord_climate_v0a"

set "TEMP_NC=C:\AkerSyncRaw\smhi\SMHI_pthbv_tas_2011_2025_monthly.nc"
set "PRECIP_NC=C:\AkerSyncRaw\smhi\SMHI_pthbv_pr_2011_2025_monthly.nc"
if not "%~1"=="" set "TEMP_NC=%~1"
if not "%~2"=="" set "PRECIP_NC=%~2"

set "HERE=%~dp0"
set "PREP=%HERE%prepare_pthbv_climate_twofiles.py"
set "MODEL=%HERE%run_climate_validation.py"
set "REQ=%HERE%climate_requirements.txt"

echo ====================================================================================
echo AkerScore x Normskord x SMHI PTHBV climate validation v0a
echo ====================================================================================
echo Temperature : %TEMP_NC%
echo Precipitation: %PRECIP_NC%
echo.

if not exist "%TEMP_NC%" (
  echo FAIL: temperature PTHBV NetCDF not found.
  echo Expected default:
  echo   %TEMP_NC%
  echo.
  echo Put the downloaded tas file there, or pass temp and precip files as arguments.
  exit /b 2
)
if not exist "%PRECIP_NC%" (
  echo FAIL: precipitation PTHBV NetCDF not found.
  echo Expected default:
  echo   %PRECIP_NC%
  echo.
  echo Put the downloaded pr file there, or pass temp and precip files as arguments.
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
%PY% "%PREP%" --temp-netcdf "%TEMP_NC%" --precip-netcdf "%PRECIP_NC%" --input-dir "%INPUT%" --local-paths "%LOCALPATHS%" --output-dir "%OUT%\climate"
if errorlevel 1 (
  echo.
  echo PTHBV parser/overlay failed. Printing temperature NetCDF structure:
  %PY% "%HERE%inspect_pthbv.py" "%TEMP_NC%"
  echo.
  echo Printing precipitation NetCDF structure:
  %PY% "%HERE%inspect_pthbv.py" "%PRECIP_NC%"
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
