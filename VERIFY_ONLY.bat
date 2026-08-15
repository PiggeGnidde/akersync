@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync - VERIFY ONLY
echo Ingen analys raknas om.
echo ============================================================
echo.
py -3 src\08_verify.py --config config\local_paths.json
if errorlevel 1 (
  python src\08_verify.py --config config\local_paths.json
)
echo.
pause
