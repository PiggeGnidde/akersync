@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
py -3 src\127_diagnose_akerfro_web_sidecars.py
exit /b %ERRORLEVEL%
