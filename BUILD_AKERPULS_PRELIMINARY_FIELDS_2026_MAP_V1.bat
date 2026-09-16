@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_preliminary_fields_2026_map_v1"
if not "%~1"=="" set "D2C=%~1"
if not "%~2"=="" set "OUT=%~2"

echo ============================================================
echo AKERPULS - PRELIMINARY FIELDS 2026 MAP V1
echo FULL SKANE: OFFICIAL 2025 BOUNDARIES + 613 FROZEN SPLIT LINES
echo ============================================================
echo D2C=%D2C%
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before map build.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%D2C%\akerpuls_preliminary_geometry_v1_freeze\AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json" (
  echo ERROR: missing frozen ÅkerPuls preliminary geometry v1
  exit /b 1
)
if not exist "%D2C%\d2c_p95_split_line_freeze_v1\P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json" (
  echo ERROR: missing frozen P95 split-line proposal package
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_preliminary_fields_2026_map_v1 tests.test_akerpuls_preliminary_fields_2026_map_v1_policyfix tests.test_akerpuls_preliminary_fields_2026_map_v1_tilefix -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build full-Skane preliminary 2026 field map
py -3 -u src\168_akerpuls_preliminary_fields_2026_map_v1_tilefix.py --d2c-dir "%D2C%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\index.html" (echo ERROR: map HTML not created& exit /b 1)
if not exist "%OUT%\akerpuls_preliminary_fields_2026_map_v1.gpkg" (echo ERROR: exact GPKG not created& exit /b 1)
if not exist "%OUT%\akerpuls_preliminary_fields_2026_map_v1_qa.json" (echo ERROR: QA JSON not created& exit /b 1)
if not exist "%OUT%\akerpuls_preliminary_fields_2026_map_v1_manifest.json" (echo ERROR: manifest not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during map build.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: full-Skane preliminary 2026 field map built for review.
echo OPEN VIA LOCAL HTTP: OPEN_AKERPULS_PRELIMINARY_FIELDS_2026_MAP_V1.bat
echo DO NOT OPEN index.html DIRECTLY AS file:// FOR OSM TILE QA.
echo EXACT GPKG: %OUT%\akerpuls_preliminary_fields_2026_map_v1.gpkg
echo NEXT STOP: visually review map before freeze.
echo ============================================================
exit /b 0
