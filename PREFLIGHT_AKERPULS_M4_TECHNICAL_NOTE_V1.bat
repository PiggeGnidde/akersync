@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "M0=C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1"
set "ZIP=C:\AkerSyncRepo\work\vaxtfoljd_prior_v1_freeze\vaxfoljd_prior_v1_freeze.zip"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_technical_note_preflight_v1"
if not "%~1"=="" set "OUT=%~1"

echo ============================================================
echo AKERPULS - M4 TECHNICAL NOTE PREFLIGHT V1
echo READ-ONLY DOCX TEXT EXTRACTION FROM FROZEN ZIP
echo ============================================================
echo M0_FREEZE_DIR=%M0%
echo VAX_ZIP=%ZIP%
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before Technical Note preflight.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%ZIP%" (echo ERROR: frozen vaxtfoljd ZIP not found: %ZIP%& exit /b 1)
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Remove only this preflight output directory if you intentionally want to rerun.
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_m4_technical_note_preflight_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Extract frozen Technical Note text in place
py -3 -u src\176_akerpuls_m4_technical_note_preflight_v1.py --m0-freeze-dir "%M0%" --vax-zip "%ZIP%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\M4_TECHNICAL_NOTE_PREFLIGHT_V1.json" (echo ERROR: metadata JSON not created& exit /b 1)
if not exist "%OUT%\M4_TECHNICAL_NOTE_EXCERPTS_V1.txt" (echo ERROR: excerpts not created& exit /b 1)
if not exist "%OUT%\M4_TECHNICAL_NOTE_TEXT_V1.txt" (echo ERROR: full text not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during Technical Note preflight.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: frozen M4 Technical Note read in place.
echo No model prediction, fusion, tuning or geometry mutation occurred.
echo.
echo Paste this file into chat:
echo %OUT%\M4_TECHNICAL_NOTE_EXCERPTS_V1.txt
echo ============================================================
exit /b 0
