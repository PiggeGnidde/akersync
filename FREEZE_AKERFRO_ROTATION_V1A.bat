@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo ====================================================================================================
echo ÅkerFrö Rotation v1.1 - FORMAL FREEZE
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

echo [1/3] Rebuild + verify candidate and impact...
CALL BUILD_AKERFRO_ROTATION_V1A.bat
if errorlevel 1 goto :fail

echo [2/3] Final audit...
CALL AUDIT_AKERFRO_ROTATION_V1A.bat
if errorlevel 1 goto :fail

echo [3/3] Write formal freeze manifest and verify hashes...
py -3 analysis\akerfro_ertor_v0a\freeze_rotation_v1a.py
if errorlevel 1 goto :fail
py -3 analysis\akerfro_ertor_v0a\verify_rotation_v1a_freeze.py
if errorlevel 1 goto :fail

echo ====================================================================================================
echo ÅKERFRO ROTATION V1.1 FORMAL FREEZE: PASS
echo ====================================================================================================
exit /b 0

:fail
echo ====================================================================================================
echo ÅKERFRO ROTATION V1.1 FORMAL FREEZE: FAIL
echo ====================================================================================================
exit /b 1
