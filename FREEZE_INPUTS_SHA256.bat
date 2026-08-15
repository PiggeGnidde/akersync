@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Detta kan ta en stund eftersom alla DEM-filer hashas.
py -3 src\00_check_inputs.py --hash-dem
pause
