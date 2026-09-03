@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python src\make_baseline.py
if errorlevel 1 exit /b %errorlevel%
echo.
echo Baseline generated and verified.
