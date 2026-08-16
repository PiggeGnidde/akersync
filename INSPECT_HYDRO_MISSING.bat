@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\04_inspect_missing_hydrology.py
pause
