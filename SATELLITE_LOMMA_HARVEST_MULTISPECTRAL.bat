@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==============================================================================
echo ÅkerSync · Satellite V1a · Lomma multispektral skördeanalys
echo ==============================================================================

py -3 src\22_satellite_lomma_harvest_multispectral.py --start 2026-07-09 --end 2026-08-16 --visual-first-combine 2026-07-28
if errorlevel 1 (
  echo.
  echo SATELLITE LOMMA HARVEST MULTISPECTRAL: FEL
  pause
  exit /b 1
)

echo.
echo SATELLITE LOMMA HARVEST MULTISPECTRAL: KLAR
pause
exit /b 0
