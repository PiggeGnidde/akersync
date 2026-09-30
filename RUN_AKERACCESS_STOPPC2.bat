@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess - STOPPUNKT C2 - FETCH NVDB + MATCH
echo ==============================================================================

py -3 analysis\akeraccess_v0a\fetch_nvdb_sjobo_c2.py
if errorlevel 1 goto :fail

echo.
py -3 analysis\akeraccess_v0a\nvdb_anchor_match_c2.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C2: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C2: FAIL
echo ==============================================================================
exit /b 1
