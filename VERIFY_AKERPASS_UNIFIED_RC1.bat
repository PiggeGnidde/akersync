@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
py -3 src\129_verify_akerpass_unified_rc1.py
exit /b %ERRORLEVEL%
