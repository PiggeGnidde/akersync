@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 analysis\akerfro_ertor_v0a\verify_operational_mvp_v0a_freeze.py
exit /b %ERRORLEVEL%
