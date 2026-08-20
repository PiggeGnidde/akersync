@echo off
setlocal
cd /d "%~dp0"

echo AkerDrift ruttpilot: 50 deterministiskt valda Lomma-skiften.
echo Resultat checkpointas efter varje skifte. Hela kommunen kors inte.
py -3 src\45_akerdrift_route_pilot.py run --kommun Lomma --limit 50
if errorlevel 1 goto :error

echo.
echo KLART. Se data\derived\akerdrift_route_pilot_v1a\lomma_50\qa
pause
exit /b 0

:error
echo.
echo FEL: ruttpiloten avbrots. Kor samma BAT-fil igen for att fortsatta fran checkpoints.
pause
exit /b 1
