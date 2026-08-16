@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================== 
echo ÅkerSync · Geometry V1a · extremer och score-fri kandidat-screen
echo ============================================================================== 
py -3 src\10_explore_geometry_v1a.py
pause
