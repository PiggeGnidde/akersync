@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync ^· Geometry V1a ^· råa skiftesmått ^· ingen score
echo ==============================================================================
py -3 src\09_geometry_v1a.py
pause
