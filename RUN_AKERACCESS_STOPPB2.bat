@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess - STOPPUNKT B2 - ELIGIBILITY + CARRY-OVER QA
echo ==============================================================================

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

echo.
echo [1/3] Unit tests...
py -3 -m unittest tests.test_akeraccess_review_b2 -v
if errorlevel 1 goto :fail

echo.
echo [2/3] Filter ^>=1 ha, remove pasture, reuse old QA and top up sample...
py -3 analysis\akeraccess_v0a\prepare_review_b2.py
if errorlevel 1 goto :fail

echo.
echo [3/3] Build B2 visual reviewer...
py -3 analysis\akeraccess_v0a\build_review_ui_b2.py
if errorlevel 1 goto :fail

set "QAHTML=%CD%\work\akeraccess_v0a\sjobo\review_b2\index.html"
echo.
echo Oppnar B2-reviewern...
start "" "%QAHTML%"

echo.
echo Bedom bara falten markerade NYTT B2-falt.
echo Nar de ar klara: klicka "Ladda ner B2 QA CSV".
echo Output: sjobo_akeraccess_visual_qa_b2.csv
echo ==============================================================================
echo AKERACCESS STOPPUNKT B2: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT B2: FAIL
echo ==============================================================================
exit /b 1
