@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ====================================================================================================
echo ÅkerFrö x ÅkerAccess BestMatch v0c - FORMAL FREEZE
echo ====================================================================================================

for /f "delims=" %%B in ('git branch --show-current') do set BRANCH=%%B
if /I not "%BRANCH%"=="feature/akerfro-bestmatch-v0c" (
  echo FAIL: expected branch feature/akerfro-bestmatch-v0c, got %BRANCH%
  exit /b 1
)

git diff --quiet
if errorlevel 1 (
  echo FAIL: tracked working tree changes present.
  git status --short
  exit /b 1
)

echo [0/4] Verify frozen upstream Rotation v1.1 and BestMatch v0b...
CALL VERIFY_AKERFRO_ROTATION_V1A_FREEZE.bat
if errorlevel 1 goto :fail
CALL VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0B_FREEZE.bat
if errorlevel 1 goto :fail

echo [1/4] Build canonical BestMatch v0c...
py -3 analysis\akeraccess_v0a\build_bestmatch_v0c_product.py
if errorlevel 1 goto :fail

echo [2/4] Verify v0c candidate...
py -3 analysis\akeraccess_v0a\verify_bestmatch_v0c.py
if errorlevel 1 goto :fail

echo [3/4] Write formal freeze manifest...
py -3 analysis\akeraccess_v0a\freeze_bestmatch_v0c.py
if errorlevel 1 goto :fail

echo [4/4] Verify formal freeze...
py -3 analysis\akeraccess_v0a\verify_bestmatch_v0c_freeze.py
if errorlevel 1 goto :fail

echo ====================================================================================================
echo BESTMATCH v0c FORMAL FREEZE: PASS
echo ====================================================================================================
exit /b 0

:fail
echo ====================================================================================================
echo BESTMATCH v0c FORMAL FREEZE: FAIL
echo ====================================================================================================
exit /b 1
