@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo [1/2] Candidate and offline safety tests...
py -3 -m unittest tests.test_rapskartan_local_candidate tests.test_rapskartan_map_product tests.test_rapskartan_parity_diagnostic -q >nul
if errorlevel 1 exit /b 1
echo [2/2] OFFLINE candidate replay. No login, downloads or map generation.
echo Uses existing scene archive. Original outputs and production thresholds remain unchanged.
py -3 -u src\102_diagnose_rapskartan_2025_parity.py --engine-profile reference_pixels_v2 --output-dir data\derived\rapskartan_v1\2025_candidate_parity_v2 %*
exit /b %ERRORLEVEL%
