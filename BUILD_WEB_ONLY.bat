@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\build_web_only.py
if errorlevel 1 python src\build_web_only.py
pause
