@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

py -3 analysis\akeraccess_v0a\verify_akeraccess_v0a_freeze.py
exit /b %ERRORLEVEL%
