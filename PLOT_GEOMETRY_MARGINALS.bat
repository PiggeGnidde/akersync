@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · O141 marginaleffekt · rectangularity x area
echo ==============================================================================
py -3 src\15_geometry_marginal_effects.py
if errorlevel 1 (
  echo.
  echo FEL: marginaleffekt-korningen misslyckades.
  pause
  exit /b 1
)
echo.
start "" "%CD%\dist\geometry_o141_rectangularity_marginals.html"
echo Graf oppnad i webblasaren.
pause
