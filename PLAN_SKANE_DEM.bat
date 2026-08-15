@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_plan_dem_skane.py --config config\local_paths.json
if errorlevel 1 (
  echo.
  echo DEM-planeringen misslyckades.
  exit /b 1
)
echo.
echo DEM-planering klar. Se data\derived\dem_plan_skane.csv och dem_plan_skane_bbox.txt
