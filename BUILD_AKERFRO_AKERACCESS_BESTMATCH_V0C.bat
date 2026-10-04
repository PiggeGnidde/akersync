@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

py -3 analysis\akeraccess_v0a\build_bestmatch_v0c_product.py
if errorlevel 1 exit /b 1
py -3 analysis\akeraccess_v0a\verify_bestmatch_v0c.py
exit /b %ERRORLEVEL%
