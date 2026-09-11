@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
if not defined AKERMINNE_ROOT set "AKERMINNE_ROOT=C:\AkerSync-Minne\data\derived\akerminne_v1a\skane"
if not exist "%AKERMINNE_ROOT%\municipalities" if exist "C:\AkerSyncRepo\data\derived\akerminne_v1a\skane\municipalities" set "AKERMINNE_ROOT=C:\AkerSyncRepo\data\derived\akerminne_v1a\skane"
set "OUT=C:\AkerSyncRepo\work\akerpuls_geometry_persistence_study_v0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

py -3 -c "import numpy,pandas,pyarrow" >nul 2>nul || (
  echo FAIL: Python dependencies numpy/pandas/pyarrow are missing in py -3 environment.
  exit /b 1
)

if not exist "%AKERMINNE_ROOT%\municipalities" (
  echo FAIL: frozen AkerMinne municipality root not found:
  echo   %AKERMINNE_ROOT%\municipalities
  echo Expected primary workspace: C:\AkerSync-Minne\data\derived\akerminne_v1a\skane
  echo You may override it by setting AKERMINNE_ROOT before running this batch.
  echo This study does not download or rebuild AkerMinne.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - GEOMETRY PERSISTENCE PRIOR STUDY - ZERO PU
 echo ========================================================================================
echo AKERMINNE_ROOT=%AKERMINNE_ROOT%

py -3 -m unittest tests.test_akerpuls_geometry_persistence_study -v
if errorlevel 1 exit /b 1

py -3 src\129_akerpuls_geometry_persistence_study.py --akerminne-root "%AKERMINNE_ROOT%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

endlocal
