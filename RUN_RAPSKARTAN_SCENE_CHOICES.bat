@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo [1/2] Offline scene-choice tests...
py -3 -m unittest tests.test_rapskartan_scene_choices tests.test_rapskartan_parity_diagnostic -q >nul
if errorlevel 1 exit /b 1
echo [2/2] Two dates, at most twelve fields and sixteen existing scenes. No login or downloads.
py -3 -u src\105_compare_rapskartan_scene_choices.py %*
exit /b %ERRORLEVEL%
