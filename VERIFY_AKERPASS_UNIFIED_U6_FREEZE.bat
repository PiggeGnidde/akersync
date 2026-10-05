@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "PY=.venv\akerpass_u5\Scripts\python.exe"
if not exist "%PY%" exit /b 1
"%PY%" src\134_verify_akerpass_u6_freeze.py
exit /b %ERRORLEVEL%
