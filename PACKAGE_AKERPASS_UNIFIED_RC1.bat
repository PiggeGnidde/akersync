@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ====================================================================================================
echo ÅkerPass Unified Preview v0a-r1 - U4 RC1 FREEZE + PACKAGE
echo ====================================================================================================

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akerpass-unified-web-v0a-r1" (
  echo FAIL: expected feature/akerpass-unified-web-v0a-r1, got %BRANCH%.
  exit /b 1
)

git diff --quiet
if errorlevel 1 (
  echo FAIL: tracked working tree changes present.
  git status --short
  exit /b 1
)

echo [0/5] Verify frozen Rotation v1.1...
call VERIFY_AKERFRO_ROTATION_V1A_FREEZE.bat
if errorlevel 1 goto :fail

echo [1/5] Verify frozen BestMatch v0c...
call VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0C_FREEZE.bat
if errorlevel 1 goto :fail

echo [2/5] Re-verify the existing QAed unified dist. NO rebuild...
py -3 src\126_verify_akerpass_unified_web_v0a.py
if errorlevel 1 goto :fail

echo [3/5] Freeze exact dist + create deterministic deploy ZIP...
py -3 src\128_package_akerpass_unified_rc1.py
if errorlevel 1 goto :fail

echo [4/5] Verify every ZIP member against the frozen dist hashes...
py -3 src\129_verify_akerpass_unified_rc1.py
if errorlevel 1 goto :fail

echo [5/5] U4 complete.
echo ====================================================================================================
echo AKERPASS UNIFIED PREVIEW U4 RC1: FREEZE / PACKAGE / VERIFY PASS
echo ====================================================================================================
echo Package: %CD%\release\akerpass_unified_preview_v0a_r1_rc1.zip
echo Manifest: %CD%\work\akerpass_unified_rc1\akerpass_unified_preview_v0a_r1_rc1_manifest.json
echo Deployment: NO
echo Next: U5 deploy exact RC1 ZIP to preview.akerpass.se and run HTTPS mobile/GPS smoke.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo AKERPASS UNIFIED PREVIEW U4 RC1: FAIL
echo ====================================================================================================
echo No deployment performed. Do not use the RC ZIP unless final verify says PASS.
exit /b 1
