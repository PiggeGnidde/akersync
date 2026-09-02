@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "TAG=akernorm-v1.0"
set "BRANCH=feature/akernorm-product-v1a"
set "PRODUCT_COMMIT=3a983560616e0211d86e49500471bf9c322626f5"
set "PRODUCT_TREE=5a938a72dd978a3b529834bd0a8c2aef09292100"

if "%~3"=="" goto :usage
set "STOPA=%~f1"
set "INPUT=%~f2"
set "BASE_DIST=%~f3"
if "%~4"=="" (set "OUT=%CD%\data\derived\akernorm_v1") else (set "OUT=%~f4")
if "%~5"=="" (set "DIST=%CD%\dist") else (set "DIST=%~f5")

echo ========================================================================================
echo AkerNorm V1 - FINAL FREEZE AND ANNOTATED TAG
echo ========================================================================================
echo STOPPUNKT A: %STOPA%
echo Frozen input: %INPUT%
echo Frozen base web: %BASE_DIST%
echo Accepted output: %OUT%
echo Local web: %DIST%
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if /I not "!CURRENT_BRANCH!"=="%BRANCH%" (
  echo ERROR: current branch is !CURRENT_BRANCH!, expected %BRANCH%.
  goto :fail
)
for /f "delims=" %%S in ('git status --porcelain') do (
  echo ERROR: working tree is not clean before freeze.
  git status --short
  goto :fail
)

echo [1/7] Fetch and verify the pushed freeze commit...
git fetch origin --tags
if errorlevel 1 goto :fail
for /f %%H in ('git rev-parse HEAD') do set "HEAD_SHA=%%H"
for /f %%H in ('git rev-parse origin/%BRANCH%') do set "REMOTE_SHA=%%H"
if /I not "!HEAD_SHA!"=="!REMOTE_SHA!" (
  echo ERROR: local HEAD !HEAD_SHA! differs from origin/%BRANCH% !REMOTE_SHA!.
  goto :fail
)
for /f %%H in ('git rev-parse HEAD~1') do set "PARENT_SHA=%%H"
if /I not "!PARENT_SHA!"=="%PRODUCT_COMMIT%" (
  echo ERROR: freeze parent !PARENT_SHA! differs from accepted product commit %PRODUCT_COMMIT%.
  goto :fail
)
where py >nul 2>nul
if errorlevel 1 (set "PY=python") else (set "PY=py -3")

echo.
echo [2/7] Run all AkerNorm unit and regression tests...
%PY% -m unittest discover -s tests -p "test_akernorm_v1_*.py" -v
if errorlevel 1 goto :fail

echo.
echo [3/7] Reverify STOPPUNKT A reproduction...
call VERIFY_AKERNORM_V1_REPRODUCTION.bat "%STOPA%"
if errorlevel 1 goto :fail

echo.
echo [4/7] Reverify local STOPPUNKT D web and protected base products...
call VERIFY_AKERNORM_V1_WEB.bat "%BASE_DIST%" "%OUT%" "%DIST%"
if errorlevel 1 goto :fail

echo.
echo [5/7] Verify every accepted A-D manifest, hash, input and freeze-scope...
%PY% src\88_verify_akernorm_v1_freeze.py --stop-a-dir "%STOPA%" --input-dir "%INPUT%" --output-root "%OUT%" --base-dist "%BASE_DIST%" --dist "%DIST%"
if errorlevel 1 goto :fail
for /f "delims=" %%S in ('git status --porcelain') do (
  echo ERROR: working tree became dirty during verification.
  git status --short
  goto :fail
)

echo.
echo [6/7] Create or verify immutable annotated tag %TAG%...
git rev-parse -q --verify "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 (
  for /f %%H in ('git rev-list -n 1 "%TAG%"') do set "TAG_SHA=%%H"
  if /I not "!TAG_SHA!"=="!HEAD_SHA!" (
    echo ERROR: %TAG% already points to !TAG_SHA!, not !HEAD_SHA!.
    echo The existing tag will NOT be moved.
    goto :fail
  )
  for /f %%T in ('git cat-file -t "refs/tags/%TAG%"') do set "TAG_TYPE=%%T"
  if /I not "!TAG_TYPE!"=="tag" (
    echo ERROR: %TAG% exists but is not an annotated tag.
    goto :fail
  )
  echo Existing annotated tag is correct.
) else (
  git tag -a "%TAG%" -m "Freeze AkerNorm V1 - source akernorm-source-2026-f03930b8a2a063de - model akernorm-model-def3710a77e7ace9 - full Skane akernorm-full-skane-38d679e0f59c3ae0 - 33 municipalities - 128636 fields - 402922 field/crop rows - no deployment or Sentinel-2"
  if errorlevel 1 goto :fail
)

echo.
echo [7/7] Push the tag and verify it on GitHub...
git push origin "refs/tags/%TAG%"
if errorlevel 1 goto :fail
git ls-remote --exit-code --tags origin "refs/tags/%TAG%" "refs/tags/%TAG%^^{}"
if errorlevel 1 (
  echo ERROR: remote annotated tag could not be verified.
  goto :fail
)
for /f "delims=" %%S in ('git status --porcelain') do (
  echo ERROR: working tree is not clean after tag push.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo AKERNORM V1 FINAL FREEZE: PASS
echo ========================================================================================
echo Tag: %TAG%
echo Commit: !HEAD_SHA!
echo Product parent: %PRODUCT_COMMIT%
echo Product tree: %PRODUCT_TREE%
echo Counts: 33 municipalities / 128636 fields / 402922 field-crop rows
echo STOPPUNKT A-D: PASS and hash verified
echo Deployment/Sentinel-2: NO
echo Annotated tag: PUSHED and remote-visible
echo.
git show --no-patch --decorate "%TAG%"
echo.
echo Return this complete console output to the code chat.
pause
exit /b 0

:usage
echo Usage:
echo   FREEZE_AKERNORM_V1.bat "STOPA_DIR" "FROZEN_INPUT_DIR" "FROZEN_BASE_DIST" [OUTPUT_ROOT] [TARGET_DIST]
exit /b 2

:fail
echo.
echo ========================================================================================
echo AKERNORM V1 FINAL FREEZE: FAIL
echo ========================================================================================
echo No existing tag is moved and no deployment or Sentinel-2 work is performed.
echo Return the complete console output and %OUT%\logs\freeze_verify_traceback.log if present.
pause
exit /b 1
