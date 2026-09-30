@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess MVP v0b - STOPPUNKT B - VISUAL QA REVIEWER
echo ==============================================================================

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 analysis\akeraccess_v0a\build_review_ui_v0b.py
if errorlevel 1 goto :fail

set "QAHTML=%CD%\work\akeraccess_v0a\sjobo\review_v0b\index.html"
echo.
echo Oppnar reviewverktyget...
start "" "%QAHTML%"

echo.
echo Nar du ar klar: klicka "Ladda ner QA CSV" i reviewverktyget.
echo Filen heter sjobo_akeraccess_visual_qa_v0b.csv
echo ==============================================================================
echo AKERACCESS STOPPUNKT B REVIEWER: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT B REVIEWER: FAIL
echo ==============================================================================
exit /b 1
