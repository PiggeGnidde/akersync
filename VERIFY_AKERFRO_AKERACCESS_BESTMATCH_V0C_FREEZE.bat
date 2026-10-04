@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
py -3 analysis\akeraccess_v0a\verify_bestmatch_v0c_freeze.py
exit /b %ERRORLEVEL%
