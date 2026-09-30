@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess - STOPPUNKT B2 RESULT + C0 ROAD NETWORK
echo ==============================================================================

echo.
echo [1/3] Network core tests...
py -3 -m unittest tests.test_akeraccess_network_core -v
if errorlevel 1 goto :fail

echo.
echo [2/3] Analyze completed B2 visual QA...
py -3 analysis\akeraccess_v0a\analyze_review_b2.py
if errorlevel 1 goto :fail

echo.
echo [3/3] Run road-network connectivity on all eligible Sjobo fields...
py -3 analysis\akeraccess_v0a\network_connectivity_c0.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS B2 + C0: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS B2 + C0: FAIL
echo ==============================================================================
exit /b 1
