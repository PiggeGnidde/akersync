@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess D1 - SKANE CONSERVART ROAD-FEATURE REPLICATION
echo ==============================================================================
echo Uses frozen D0 output only. No API calls.
echo Primary replication excludes Sjobo.
echo.

py -3 analysis\akeraccess_v0a\skane_pea_replication_d1.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS D1 SKANE REPLICATION: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS D1 SKANE REPLICATION: FAIL
echo ==============================================================================
exit /b 1
