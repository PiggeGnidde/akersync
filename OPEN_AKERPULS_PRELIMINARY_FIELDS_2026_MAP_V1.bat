@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "OUT=C:\AkerSyncRepo\work\akerpuls_preliminary_fields_2026_map_v1"
set "PORT=8765"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "PORT=%~2"

if not exist "%OUT%\index.html" (
  echo ERROR: missing %OUT%\index.html
  exit /b 1
)

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)

echo Starting local HTTP server on http://127.0.0.1:%PORT%/
start "AkerPulsMapServer" /min py -3 -m http.server %PORT% --bind 127.0.0.1 --directory "%OUT%"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%PORT%/index.html"

echo MAP=http://127.0.0.1:%PORT%/index.html
echo Leave the AkerPulsMapServer window/process running while reviewing the map.
exit /b 0
