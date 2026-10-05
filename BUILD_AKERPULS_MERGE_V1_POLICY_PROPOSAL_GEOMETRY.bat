@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_v1_policy_proposal_geometry_v1"

echo ============================================================
echo AKERPULS - FREEZE MERGE-V1 POLICY + BUILD PROPOSAL GEOMETRY
echo Canonical 2025 geometry; split + merge overlays only
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (echo ERROR: output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Policy/package contract tests
py -3 -m unittest tests.test_akerpuls_merge_v1_policy_proposal_geometry -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify frozen lineage and build exact proposal-only geometry package
py -3 -u src\211_akerpuls_merge_v1_policy_proposal_geometry.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\akerpuls_2026_proposal_geometry_v1.gpkg" (echo ERROR: GPKG missing& exit /b 1)
if not exist "%OUT%\AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1.json" (echo ERROR: policy freeze missing& exit /b 1)

echo.
echo ============================================================
echo PASS: merge-v1 policy frozen and proposal-only geometry built.
echo STOP HERE and paste output before final Skane review map.
echo ============================================================
exit /b 0
