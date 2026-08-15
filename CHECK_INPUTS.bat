@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_check_inputs.py
pause
