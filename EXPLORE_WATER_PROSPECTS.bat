@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\explore_water_prospects.py
pause
