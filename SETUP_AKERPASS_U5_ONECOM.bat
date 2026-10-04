@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set "PY=.venv\akerpass_u5\Scripts\python.exe"
if not exist "%PY%" (
  echo [setup] Creating isolated deploy venv...
  py -3 -m venv .venv\akerpass_u5
  if errorlevel 1 exit /b 1
)
"%PY%" -c "import paramiko" >nul 2>nul
if errorlevel 1 (
  echo [setup] Installing Paramiko into isolated deploy venv...
  "%PY%" -m pip install --disable-pip-version-check "paramiko>=3.4,<4"
  if errorlevel 1 exit /b 1
)
"%PY%" src\130_setup_akerpass_u5_onecom.py
exit /b %ERRORLEVEL%
