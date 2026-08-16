@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\09_soil_extremes.py
pause
