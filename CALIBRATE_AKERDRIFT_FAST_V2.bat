@echo off
setlocal
cd /d "%~dp0"

py -3 src\46_calibrate_akerdrift_fast_v2.py ^
  --input data\derived\akerdrift_route_pilot_v1a_rc1_1\lomma_200 ^
  --input data\derived\akerdrift_route_pilot_v1a_rc1_1\eslov_200 ^
  --input data\derived\akerdrift_route_pilot_v1a_rc1_1\simrishamn_200 ^
  --output-dir data\derived\akerdrift_fast_v2_calibration

if errorlevel 1 (
  echo.
  echo FEL: Fast V2-kalibreringen misslyckades.
  pause
  exit /b 1
)

echo.
echo KLART. Se data\derived\akerdrift_fast_v2_calibration
pause
