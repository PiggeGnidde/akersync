@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas. Kor SETUP_PATHS.bat forst.
  pause
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  python src\44_akerdrift_fast_v1.py run --all --resume
) else (
  py -3 src\44_akerdrift_fast_v1.py run --all --resume
)
if errorlevel 1 goto :error

echo.
echo KLART: 33 kommuncheckpoints och sammanslagen Skane-fil.
echo QA startas INTE automatiskt. Kor CHECK_AKERDRIFT_FAST_V1.bat separat.
pause
exit /b 0

:error
echo.
echo FEL: Korningen stannade. Starta samma BAT igen; giltiga kommuncheckpoints hoppas over.
pause
exit /b 1
