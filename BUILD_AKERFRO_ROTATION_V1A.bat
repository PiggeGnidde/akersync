@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo ====================================================================================================
echo ÅkerFrö Rotation v1.1 candidate + BestMatch impact
echo ====================================================================================================

for /f "delims=" %%B in ('git branch --show-current') do set BRANCH=%%B
if /I not "%BRANCH%"=="feature/akerfro-rotation-v1a" (
  echo FAIL: expected branch feature/akerfro-rotation-v1a, got %BRANCH%
  exit /b 1
)

git diff --quiet
if errorlevel 1 (
  echo FAIL: tracked working tree changes present.
  git status --short
  exit /b 1
)

echo [0/5] Verify frozen upstream products...
call VERIFY_AKERFRO_OPERATIONAL_MVP_V0A_FREEZE.bat
if errorlevel 1 goto :fail
call VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0B_FREEZE.bat
if errorlevel 1 goto :fail

echo [1/5] Build Rotation v1.1 downstream candidate...
py -3 analysis\akerfro_ertor_v0a\build_rotation_v1a.py
if errorlevel 1 goto :fail

echo [2/5] Verify Rotation v1.1...
py -3 analysis\akerfro_ertor_v0a\verify_rotation_v1a.py
if errorlevel 1 goto :fail

echo [3/5] Evaluate frozen BestMatch policy under v1.1 eligibility...
py -3 analysis\akeraccess_v0a\evaluate_bestmatch_rotation_v1a.py
if errorlevel 1 goto :fail

echo [4/5] Verify BestMatch impact...
py -3 analysis\akeraccess_v0a\verify_bestmatch_rotation_v1a_impact.py
if errorlevel 1 goto :fail

echo [5/5] Complete.
echo ====================================================================================================
echo AKERFRO ROTATION V1.1: BUILD PASS / VERIFY PASS / BESTMATCH IMPACT PASS
echo ====================================================================================================
echo No frozen v0a/v0b product modified. No preview deployment performed.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo AKERFRO ROTATION V1.1: FAIL
echo ====================================================================================================
echo No deployment performed.
exit /b 1
