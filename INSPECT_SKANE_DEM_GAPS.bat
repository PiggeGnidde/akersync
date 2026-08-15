@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\00_inspect_dem_gaps.py --config config\local_paths.json --missing data\derived\dem_still_missing_skane.csv
