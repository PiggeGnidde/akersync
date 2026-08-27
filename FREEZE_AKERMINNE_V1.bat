@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "TAG=akerminne-v1.0"
set "EXPECTED_BRANCH=feature/akerminne-v1a"

echo ==============================================================================
echo AkerMinne v1.0 - FREEZE
 echo ==============================================================================
echo This runner verifies the frozen implementation, creates an annotated tag,
echo and pushes only that tag to origin. It does not merge, rebase or force-push.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FEL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

for /f "delims=" %%S in ('git status --short') do (
  echo FEL: working tree is not clean. Stop before freeze.
  git status --short
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

echo [1/5] Fetch tags from origin...
git fetch --tags origin
if errorlevel 1 exit /b 1

for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEADSHA=%%H"

git show-ref --verify --quiet "refs/tags/%TAG%"
if not errorlevel 1 (
  for /f "delims=" %%T in ('git rev-list -n 1 "%TAG%"') do set "TAGSHA=%%T"
  if /I not "%TAGSHA%"=="%HEADSHA%" (
    echo FEL: tag %TAG% already exists locally and points to another commit.
    echo HEAD: %HEADSHA%
    echo TAG : %TAGSHA%
    exit /b 1
  )
  echo Tag %TAG% already exists locally at current HEAD; verification continues.
)

echo.
echo [2/5] Unit tests...
py -3 -m unittest discover -s tests -p "test_akerminne*.py" -v
if errorlevel 1 exit /b 1

echo.
echo [3/5] Skurup regression...
CALL VERIFY_AKERMINNE_SKURUP_REGRESSION.bat
if errorlevel 1 exit /b 1

echo.
echo [4/5] Full Skane web QA...
py -3 src\69_verify_akerminne_skane_web.py
if errorlevel 1 exit /b 1

for /f "delims=" %%S in ('git status --short') do (
  echo FEL: verification changed tracked files; freeze aborted.
  git status --short
  exit /b 1
)

echo.
echo [5/5] Annotated immutable baseline tag...
git show-ref --verify --quiet "refs/tags/%TAG%"
if errorlevel 1 (
  git tag -a "%TAG%" -m "Freeze AkerMinne v1.0 - Skane 2015-2025 - 128636 fields - 1414996 field-years - 2935686 components - 0 unknown crop combinations"
  if errorlevel 1 exit /b 1
)

git push origin "%TAG%"
if errorlevel 1 (
  echo FEL: tag push failed. No force operation was attempted.
  exit /b 1
)

echo.
echo ==============================================================================
echo AKERMINNE v1.0 FREEZE: PASS
 echo ==============================================================================
git show --no-patch --decorate "%TAG%"
echo.
echo Frozen tag: %TAG%
echo Freeze contract: docs\AKERMINNE_V1_FREEZE.md
exit /b 0
