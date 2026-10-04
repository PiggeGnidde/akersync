@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "PY=.venv\akerpass_u5\Scripts\python.exe"
if not exist "%PY%" (
  echo FAIL: run SETUP_AKERPASS_U5_ONECOM.bat first.
  exit /b 1
)
"%PY%" src\132_verify_akerpass_u5_hosted.py
exit /b %ERRORLEVEL%
