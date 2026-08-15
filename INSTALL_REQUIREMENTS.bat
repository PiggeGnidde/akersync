@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install --upgrade -r requirements.txt
pause
