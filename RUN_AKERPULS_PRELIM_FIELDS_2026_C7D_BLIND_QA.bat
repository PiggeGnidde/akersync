@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "C7C=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation"
set "RASTER=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7b_rasters"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7d_blind_fusion_qa"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)
py -3 -c "import numpy,pandas,geopandas,rasterio,scipy,shapely,PIL" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "%C7C%\c7c_fusion_candidates.csv" (echo FAIL: C7C fusion candidates missing.& exit /b 1)
if not exist "%C7C%\c7c_summary.json" (echo FAIL: C7C summary missing.& exit /b 1)
if not exist "%RASTER%\c7b_manifest.json" (echo FAIL: C7B raster manifest missing.& exit /b 1)
if not exist "%PILOT%\c7a_pilot_fields_2025.gpkg" (echo FAIL: C7A pilot geometry missing.& exit /b 1)
if not exist "%PILOT%\FUSION_SCORE_FREEZE_BEFORE_C7.json" (echo FAIL: frozen fusion artifact missing.& exit /b 1)

 echo ========================================================================================
 echo AkerPuls 2026 - C7D BLIND FUSION QA - ALL P90 + NEAR-P90 CONTROLS - ZERO PU
 echo ========================================================================================

py -3 -m unittest tests.test_akerpuls_c7d_blind_fusion_qa -v
if errorlevel 1 exit /b 1

py -3 src\136_akerpuls_c7d_blind_fusion_qa.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

 echo.
 echo Review images only in:
 echo   %OUT%\blind_images
 echo.
 echo IMPORTANT: do NOT open c7d_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv before labels are frozen.
 echo Label C7D_01..C7D_20 using TYDLIG / MOJLIG / TVEKSAM / FALSK and paste labels back to ChatGPT.

endlocal
