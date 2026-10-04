@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerPass Unified Preview Web v0a-r1 - Rotation v1.1 + BestMatch v0c
echo ====================================================================================================

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree must be clean before unified build.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerpass-unified-web-v0a-r1" (
  echo FAIL: expected feature/akerpass-unified-web-v0a-r1, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

echo [0/4] Verify frozen Rotation v1.1...
call VERIFY_AKERFRO_ROTATION_V1A_FREEZE.bat
if errorlevel 1 goto :fail

echo [1/4] Verify frozen BestMatch v0c...
call VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0C_FREEZE.bat
if errorlevel 1 goto :fail

echo.
echo [2/4] Build unified dist from frozen products...
py -3 src\125_build_akerpass_unified_web_v0a.py
if errorlevel 1 goto :fail

echo.
echo [3/4] Independent unified verifier...
py -3 src\126_verify_akerpass_unified_web_v0a.py
if errorlevel 1 goto :fail

echo.
echo [4/4] U3-r1 integration complete.
echo ====================================================================================================
echo AKERPASS UNIFIED WEB U3-R1: BUILD PASS / VERIFY PASS
echo ====================================================================================================
echo Dist: %CD%\dist_akerpass_unified_v0a
echo Manifest: %CD%\work\akerpass_unified_web_v0a\dist_manifest.json
echo Next: CALL START_AKERPASS_UNIFIED_WEB_V0A.bat
echo No deployment performed.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo AKERPASS UNIFIED WEB U3-R1: FAIL
echo ====================================================================================================
echo No deployment performed. Return the error above.
exit /b 1
