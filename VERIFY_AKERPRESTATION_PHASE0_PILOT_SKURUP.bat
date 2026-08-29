@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
py -3 src\72_verify_akerprestation_phase0_pilot.py
exit /b %ERRORLEVEL%
