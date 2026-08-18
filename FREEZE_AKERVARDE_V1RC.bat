@echo off
setlocal
cd /d "%~dp0"

echo ========================================================================================
echo AkerSync - FREEZE AkerVarde v1.0-rc1 before 2018/2019 blind backtest
echo ========================================================================================

echo.
echo This reruns the already selected S70_NOFOREST / BASE model and writes a local freeze artifact.
echo No model selection is performed here.
echo.

python src\21_freeze_akervarde_v1rc.py
if errorlevel 1 (
  echo.
  echo ERROR: freeze failed.
  pause
  exit /b 1
)

echo.
echo Freeze complete.
echo Next recommended step:
echo   git tag -a akervarde-v1.0-rc1 -m "Frozen before 2018-2019 blind backtest"
echo   git push origin akervarde-v1.0-rc1

echo.
pause
endlocal
