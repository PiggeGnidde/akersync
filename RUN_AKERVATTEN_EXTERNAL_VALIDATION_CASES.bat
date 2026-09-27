@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d %~dp0

for /f "delims=" %%B in ('git branch --show-current') do set BRANCH=%%B
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,pyarrow,pyproj"
if errorlevel 1 exit /b 1

py -3 src\107_akervatten_external_validation_cases.py
if errorlevel 1 goto fail

echo RUN_AKERVATTEN_EXTERNAL_VALIDATION_CASES: PASS
exit /b 0

:fail
echo RUN_AKERVATTEN_EXTERNAL_VALIDATION_CASES: FAIL
exit /b 1
