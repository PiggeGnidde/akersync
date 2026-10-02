@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerPass Unified Preview Web v0a - BUILD + VERIFY
echo ====================================================================================================

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree must be clean before unified build.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerpass-unified-web-v0a" (
  echo FAIL: expected feature/akerpass-unified-web-v0a, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

echo [0/3] Verify frozen BestMatch v0b...
call VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0B_FREEZE.bat
if errorlevel 1 goto :fail

echo.
echo [1/3] Build unified dist from frozen web products...
py -3 src\125_build_akerpass_unified_web_v0a.py
if errorlevel 1 goto :fail

echo.
echo [2/3] Independent unified verifier...
py -3 src\126_verify_akerpass_unified_web_v0a.py
if errorlevel 1 goto :fail

echo.
echo [3/3] U2 complete.
echo ====================================================================================================
echo AKERPASS UNIFIED WEB U2: BUILD PASS / VERIFY PASS
echo ====================================================================================================
echo Dist: %CD%\dist_akerpass_unified_v0a
echo Manifest: %CD%\work\akerpass_unified_web_v0a\dist_manifest.json
echo Next: CALL START_AKERPASS_UNIFIED_WEB_V0A.bat
echo No deployment performed.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo AKERPASS UNIFIED WEB U2: FAIL
echo ====================================================================================================
echo No deployment performed. Return the error above.
exit /b 1
