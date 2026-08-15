@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\00_prepare_dem_downloader_skane.ps1"
if errorlevel 1 (
  echo.
  echo Forberedelsen av Skane-downloadern misslyckades.
  exit /b 1
)
