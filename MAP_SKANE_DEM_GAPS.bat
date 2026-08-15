@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_map_dem_gaps.py
