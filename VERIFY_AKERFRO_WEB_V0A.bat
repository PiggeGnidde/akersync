@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if "%~1"=="" goto :usage
set "BASE=%~f1"
set "DIST=%~dp0dist"
if not "%~2"=="" set "DIST=%~f2"
set "WORK=%~dp0work\akerfro_web_v0a"

where py >nul 2>nul
if errorlevel 1 exit /b 1

py -3 src\90_verify_akerfro_web_v0a.py --base-dist "%BASE%" --dist "%DIST%" --work "%WORK%"
exit /b %ERRORLEVEL%

:usage
echo Usage:
echo   VERIFY_AKERFRO_WEB_V0A.bat "AKERNORM_BASE_DIST" ["TARGET_DIST"]
exit /b 2
