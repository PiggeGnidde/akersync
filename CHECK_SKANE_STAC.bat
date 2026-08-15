@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
py -3 src\00_stac_dem_skane.py --config config\local_paths.json
if errorlevel 1 (
  echo.
  echo STAC-kontrollen misslyckades.
  pause
  exit /b 1
)
echo.
echo STAC-plan klar. Inga DEM-filer laddades ned.
pause
