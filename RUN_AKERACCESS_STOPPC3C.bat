@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess - STOPPUNKT C3c - ENCLAVE / NO-DIRECT-ROAD TEST
echo ==============================================================================

py -3 analysis\akeraccess_v0a\pea_enclave_c3c.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C3c: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C3c: FAIL
echo ==============================================================================
exit /b 1
