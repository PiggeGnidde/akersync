@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_set_jv_skane_2025.py
if errorlevel 1 exit /b 1
