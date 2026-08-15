@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\07_build_web.py
if errorlevel 1 python src\07_build_web.py
pause
