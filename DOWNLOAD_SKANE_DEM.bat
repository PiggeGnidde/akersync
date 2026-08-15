@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo AkerSync - download current Lantmateriet Skane DEM COGs
echo Credentials are prompted and are NOT saved.
echo ============================================================
echo.
py -3 src\00_stac_dem_skane.py --config config\local_paths.json --download --update-config
if errorlevel 1 (
  echo.
  echo DEM-nedladdningen misslyckades eller avbrots.
  pause
  exit /b 1
)
echo.
echo SKANE DEM KLART. config\local_paths.json pekar nu pa dem_skane.
pause
