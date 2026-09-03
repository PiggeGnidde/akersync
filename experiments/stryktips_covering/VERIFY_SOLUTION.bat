@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
if "%~1"=="" (
  python src\verify.py solutions\k243_linear.txt
) else (
  python src\verify.py "%~1"
)
exit /b %errorlevel%
