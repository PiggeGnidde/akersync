@echo off
setlocal
cd /d "%~dp0"

echo AkerDrift ruttpilot RC1: 150 normalfalt + 50 stressfalt i Lomma.
echo Resultat checkpointas efter varje skifte. Hela kommunen kors inte.
py -3 src\45_akerdrift_route_pilot.py run --kommun Lomma --limit 200
if errorlevel 1 goto :error

echo.
echo KLART. Se data\derived\akerdrift_route_pilot_v1a_rc1\lomma_200\qa
pause
exit /b 0

:error
echo.
echo FEL: ruttpiloten avbrots. Kor samma BAT-fil igen for att fortsatta fran checkpoints.
pause
exit /b 1
