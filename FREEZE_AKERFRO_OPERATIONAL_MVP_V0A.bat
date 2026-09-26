@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro operational MVP v0a - FORMAL FREEZE
echo ==============================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 analysis\akerfro_ertor_v0a\freeze_operational_mvp_v0a.py
if errorlevel 1 exit /b 1

CALL VERIFY_AKERFRO_OPERATIONAL_MVP_V0A_FREEZE.bat
exit /b %ERRORLEVEL%
