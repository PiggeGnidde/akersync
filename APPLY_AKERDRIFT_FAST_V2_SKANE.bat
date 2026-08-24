@echo off
setlocal
cd /d "%~dp0"

echo AkerDrift Fast V2 Hybrid RC1: kandidatkorning over hela Skane.
echo Fast V1 och AkerPass-webben andras inte.
py -3 src\47_apply_akerdrift_fast_v2.py

if errorlevel 1 (
  echo.
  echo FEL: Fast V2-kandidatkorningen misslyckades.
  pause
  exit /b 1
)

echo.
echo KLART. Granska data\derived\akerdrift_fast_v2_hybrid_rc1\qa
pause
