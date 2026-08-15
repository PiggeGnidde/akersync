@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\build_all.py --reuse-hydro
pause
