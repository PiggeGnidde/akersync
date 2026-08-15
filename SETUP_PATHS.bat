@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_setup_paths.py
if errorlevel 1 python src\00_setup_paths.py
pause
