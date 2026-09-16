@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "TAG=akerpuls-preliminary-geometry-v1.0"
set "TARGET_COMMIT=bd77e387599f1440b3b403bf88f0d00f19f96fb9"
set "EXPECTED_FREEZE_SHA256=c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
if not "%~1"=="" set "D2C=%~1"
set "FREEZE_FILE=%D2C%\akerpuls_preliminary_geometry_v1_freeze\AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json"

echo ============================================================
echo AKERPULS PRELIMINARY GEOMETRY V1 - ANNOTATED GIT TAG
echo TAG=%TAG%
echo TARGET_COMMIT=%TARGET_COMMIT%
echo EXPECTED_FREEZE_SHA256=%EXPECTED_FREEZE_SHA256%
echo ============================================================
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before tagging.
  git status --short
  exit /b 1
)

git cat-file -e "%TARGET_COMMIT%^{commit}" 2>nul
if errorlevel 1 (
  echo ERROR: target commit is not available locally: %TARGET_COMMIT%
  exit /b 1
)

if not exist "%FREEZE_FILE%" (
  echo ERROR: missing frozen v1 file:
  echo %FREEZE_FILE%
  exit /b 1
)

for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%FREEZE_FILE%').Hash.ToLower()"`) do set "GOT_FREEZE_SHA256=%%H"
if not defined GOT_FREEZE_SHA256 (
  echo ERROR: could not calculate freeze SHA256.
  exit /b 1
)
if /I not "%GOT_FREEZE_SHA256%"=="%EXPECTED_FREEZE_SHA256%" (
  echo ERROR: freeze SHA mismatch.
  echo EXPECTED=%EXPECTED_FREEZE_SHA256%
  echo GOT=%GOT_FREEZE_SHA256%
  exit /b 1
)
echo FREEZE_SHA256_VERIFIED=%GOT_FREEZE_SHA256%

echo.
echo Fetching existing tags from origin...
git fetch --tags origin
if errorlevel 1 exit /b 1

set "EXISTING_TARGET="
for /f "delims=" %%T in ('git rev-parse -q --verify "refs/tags/%TAG%^{commit}" 2^>nul') do set "EXISTING_TARGET=%%T"
if defined EXISTING_TARGET (
  if /I not "%EXISTING_TARGET%"=="%TARGET_COMMIT%" (
    echo ERROR: tag %TAG% already exists but points to %EXISTING_TARGET%
    echo Expected %TARGET_COMMIT%
    exit /b 1
  )
  echo TAG_ALREADY_EXISTS_AND_IS_CORRECT=TRUE
) else (
  echo Creating annotated tag...
  git tag -a "%TAG%" "%TARGET_COMMIT%" -m "AkerPuls preliminary geometry v1.0" -m "Freeze SHA256: %EXPECTED_FREEZE_SHA256%" -m "Official 2025 geometry remains canonical; 2026 geometry is proposal-only. P95=618; PRELIM_2026_SPLIT_PROPOSAL=613; NO_GEOMETRY_PROPOSAL=5; smoothing=false; gap_filling=false."
  if errorlevel 1 exit /b 1
)

for /f "delims=" %%T in ('git rev-parse "%TAG%^{commit}"') do set "LOCAL_TAG_TARGET=%%T"
if /I not "%LOCAL_TAG_TARGET%"=="%TARGET_COMMIT%" (
  echo ERROR: local tag target verification failed: %LOCAL_TAG_TARGET%
  exit /b 1
)

echo.
echo Pushing tag to origin...
git push origin "refs/tags/%TAG%"
if errorlevel 1 exit /b 1

echo.
echo ============================================================
echo STATUS=TAGGED_AKERPULS_PRELIMINARY_GEOMETRY_V1
echo TAG=%TAG%
echo TAG_TARGET_COMMIT=%LOCAL_TAG_TARGET%
echo PRELIMINARY_GEOMETRY_V1_FREEZE_SHA256=%EXPECTED_FREEZE_SHA256%
echo REMOTE=origin
echo ============================================================
exit /b 0
