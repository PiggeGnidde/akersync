@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess MVP v0a - STOPPUNKT A - OSM ENTRY DISCOVERY - SJOBO
echo ==============================================================================

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

echo.
echo [1/2] Unit tests...
py -3 -m unittest tests.test_akeraccess_entry_discovery_v0a -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Sjobo OSM entry discovery...
py -3 analysis\akeraccess_v0a\entry_discovery_v0a.py --kommun Sjöbo
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT A: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT A: FAIL
echo ==============================================================================
exit /b 1
