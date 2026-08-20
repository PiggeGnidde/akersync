@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  python src\44_akerdrift_fast_v1.py qa
  if errorlevel 1 goto :error
  python src\44_akerdrift_fast_v1.py sensitivity
) else (
  py -3 src\44_akerdrift_fast_v1.py qa
  if errorlevel 1 goto :error
  py -3 src\44_akerdrift_fast_v1.py sensitivity
)
if errorlevel 1 goto :error

echo.
echo KLART: separat QA och billig sensitivitet.
pause
exit /b 0

:error
echo.
echo FEL: QA avbrots. Huvudresultaten ar ororda.
pause
exit /b 1
