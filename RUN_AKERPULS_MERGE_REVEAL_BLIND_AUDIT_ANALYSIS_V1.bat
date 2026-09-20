@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_v1"

echo ============================================================
echo AKERPULS - REVEAL FROZEN BLIND MERGE AUDIT
echo LABELS ARE FORMALLY FROZEN; BLIND KEY MAY NOW BE READ
echo PREDECLARED HH/HL/LH/LL CONTRASTS ONLY
echo ============================================================
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before reveal analysis.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (
  echo ERROR: reveal-analysis output already exists: %OUT%
  echo Preserve prior evidence; do not overwrite.
  exit /b 1
)

echo.
echo [1/2] Reveal-analysis contract tests
py -3 -m unittest tests.test_akerpuls_merge_reveal_blind_audit_analysis_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Reveal frozen key and execute predeclared contrasts
py -3 -u src\195_akerpuls_merge_reveal_blind_audit_analysis_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\MERGE_AUDIT_REVEAL_ANALYSIS_SUMMARY_V1.json" (echo ERROR: reveal summary missing& exit /b 1)
if not exist "%OUT%\MERGE_AUDIT_PREDECLARED_CONTRASTS.csv" (echo ERROR: contrast table missing& exit /b 1)
if not exist "%OUT%\SHA256_MANIFEST.txt" (echo ERROR: reveal manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during reveal analysis.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: frozen blind audit revealed and predeclared contrasts computed.
echo No fusion weight/sign, threshold retuning, automatic merge or geometry mutation.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect results before any fusion decision.
echo ============================================================
exit /b 0
