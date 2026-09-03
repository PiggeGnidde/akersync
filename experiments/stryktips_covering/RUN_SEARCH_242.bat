@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python src\search.py --target 242 --minutes 10 --seed 1
echo.
echo Search exit code: %errorlevel%
echo A nonzero code means "not found in this time budget", not a verifier failure.
