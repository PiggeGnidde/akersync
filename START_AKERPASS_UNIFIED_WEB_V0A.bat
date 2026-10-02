@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PORT=8012"
if not "%~1"=="" set "PORT=%~1"
if not exist "dist_akerpass_unified_v0a\index.html" (
  echo FAIL: dist_akerpass_unified_v0a\index.html missing. Run BUILD_AKERPASS_UNIFIED_WEB_V0A.bat first.
  exit /b 1
)
echo AkerPass Unified Preview v0a: http://localhost:%PORT%/
start "" "http://localhost:%PORT%/"
py -3 -m http.server %PORT% --directory dist_akerpass_unified_v0a
