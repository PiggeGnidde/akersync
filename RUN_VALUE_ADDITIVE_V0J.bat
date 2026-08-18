@echo off
setlocal
cd /d %~dp0

echo ================================================================================
echo AkerSync - Value Regression v0j - anchored additive property decomposition
echo ================================================================================
echo.
echo Uses v0i/v0h feature output already on disk.
echo Taxeringsvarde is NOT used as target or predictor in this model.
echo Beskaffenhet and drainage are explicit arable-price variables.
echo.

if not exist "src\20j_value_additive_property_v0j.py" (
  echo ERROR: src\20j_value_additive_property_v0j.py not found.
  pause
  exit /b 1
)

py -3 src\20j_value_additive_property_v0j.py
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
  echo v0j FAILED with exit code %RC%.
  pause
  exit /b %RC%
)

echo v0j complete.
echo Output: data\derived\value_regression_v0j_additive
echo.
pause
endlocal
