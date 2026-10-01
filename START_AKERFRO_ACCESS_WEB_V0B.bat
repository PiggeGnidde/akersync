@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PORT=8011"
echo AkerFro x AkerAccess whole-Skane preview: http://localhost:%PORT%/
start "" "http://localhost:%PORT%/"
py -3 -m http.server %PORT% --directory dist_akerfro_access_v0b
