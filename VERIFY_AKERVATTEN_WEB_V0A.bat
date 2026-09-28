@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "BASE=C:\AkerSync-AkerFroWeb\dist"
if not "%~1"=="" set "BASE=%~f1"
py -3 src\113_verify_akervatten_web_v0a.py --base-dist "%BASE%" --dist "%~dp0dist" --work "%~dp0work\akervatten_web_v0a"
exit /b %errorlevel%
