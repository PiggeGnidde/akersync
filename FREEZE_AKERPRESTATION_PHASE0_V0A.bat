@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "TAG=akerprestation-phase0-v0a"
set "EXPECTED_BRANCH=feature/akerprestation-phase0-freeze-v0a"

echo ================================================================================================
echo ÅkerPrestation phase 0 - FREEZE v0a
echo ================================================================================================
echo This runner verifies the already-passed full-Skåne phase 0 artifacts,
echo then creates and pushes one annotated immutable tag. No web, merge or model phase is run.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR_FREEZE: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR_FREEZE: working tree is not clean. Stop before freeze.
  git status --short
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR_FREEZE: Python launcher py not found.
  exit /b 1
)

echo [1/5] Fetch tags from origin...
git fetch origin --tags
if errorlevel 1 exit /b 1

for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEADSHA=%%H"

git show-ref --verify --quiet "refs/tags/%TAG%"
if not errorlevel 1 (
  for /f "delims=" %%T in ('git rev-list -n 1 "%TAG%"') do set "TAGSHA=%%T"
  if /I not "%TAGSHA%"=="%HEADSHA%" (
    echo ERROR_FREEZE: tag %TAG% already exists and points to another commit.
    echo HEAD: %HEADSHA%
    echo TAG : %TAGSHA%
    exit /b 1
  )
  echo Tag %TAG% already exists locally at current HEAD; verification continues.
)

echo.
echo [2/5] Phase 0 unit/regression tests...
py -3 -m unittest discover -s tests -p "test_akerprestation_phase0_*.py" -v
if errorlevel 1 (
  echo ERROR_FREEZE: phase 0 tests failed.
  exit /b 1
)

echo.
echo [3/5] Independent full-Skåne artifact verification...
py -3 src\75_verify_akerprestation_phase0_skane.py
if errorlevel 1 (
  echo ERROR_FREEZE: independent full-Skåne verification failed.
  exit /b 1
)

echo.
echo [4/5] Immutable freeze contract preflight...
py -3 src\76_verify_akerprestation_phase0_freeze.py
if errorlevel 1 (
  echo ERROR_FREEZE: freeze contract preflight failed.
  exit /b 1
)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR_FREEZE: verification changed tracked files; freeze aborted.
  git status --short
  exit /b 1
)

echo.
echo [5/5] Annotated immutable tag...
git show-ref --verify --quiet "refs/tags/%TAG%"
if errorlevel 1 (
  git tag -a "%TAG%" -m "Freeze ÅkerPrestation phase 0 v0a - Skåne static context - 33 municipalities - 128636 fields - agricultural classes 1-10 - 18 SKO IDs - 0 unverified class/SKO components"
  if errorlevel 1 exit /b 1
)

git push origin "%TAG%"
if errorlevel 1 (
  echo ERROR_FREEZE: tag push failed. No force operation was attempted.
  exit /b 1
)

echo.
echo ================================================================================================
echo ÅKERPRESTATION PHASE 0 FREEZE: PASS
echo ================================================================================================
git show --no-patch --decorate "%TAG%"
echo.
echo Frozen tag: %TAG%
echo Freeze contract: docs\AKERPRESTATION_PHASE0_FREEZE.md
echo Validated data-build commit: 92c1e92535ac636e50b522f93c0e675c2b6f63ed
echo.
echo STOPPUNKT D - no web branch or web files were changed by this runner.
echo Return the PASS summary and git show output before web integration continues.
exit /b 0
