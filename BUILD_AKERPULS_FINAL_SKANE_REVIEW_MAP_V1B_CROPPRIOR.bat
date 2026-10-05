@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_final_skane_review_map_v1b_cropprior"

echo ============================================================
echo AKERPULS - FINAL SKANE REVIEW MAP V1B + BLIND M4 TOP-3
echo Clickable fields + thicker 2025 boundaries + split hover/drop
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%\AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR_MANIFEST.json" (
  echo ERROR: completed output already exists: %OUT%
  exit /b 1
)
if exist "%OUT%" (
  echo Removing incomplete previous v1b output: %OUT%
  rmdir /s /q "%OUT%"
  if exist "%OUT%" (echo ERROR: could not remove incomplete output& exit /b 1)
)

echo.
echo [1/2] V1b contract tests
py -3 -m unittest tests.test_akerpuls_final_skane_review_map_v1b_cropprior -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build clickable crop-prior benchmark map from frozen inputs
py -3 -u src\213_akerpuls_final_skane_review_map_v1b_cropprior.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\index.html" (echo ERROR: map index missing& exit /b 1)
if not exist "%OUT%\AKERMINNE_M4_2026_TOP3_BENCHMARK.parquet" (echo ERROR: benchmark parquet missing& exit /b 1)
if not exist "%OUT%\AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR_MANIFEST.json" (echo ERROR: manifest missing& exit /b 1)

echo.
echo ============================================================
echo PASS: v1b map + frozen blind Top-3 benchmark built.
echo NEXT: OPEN_AKERPULS_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR.bat
echo ============================================================
exit /b 0
