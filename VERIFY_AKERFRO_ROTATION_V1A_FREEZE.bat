@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
py -3 analysis\akerfro_ertor_v0a\verify_rotation_v1a_freeze.py
exit /b %ERRORLEVEL%
