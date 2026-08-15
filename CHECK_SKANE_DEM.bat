@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_check_dem_skane.py --dem C:\AkerSyncRaw\dem_skane_2p5km
if errorlevel 1 (
  echo.
  echo Skane DEM ar inte komplett annu.
  exit /b 1
)
