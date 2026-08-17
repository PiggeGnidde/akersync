@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================== 
echo ÅkerSync · Value Regression v0a · ATL punkt - jord - TWI - topografi - geometri
echo ============================================================================== 
echo.
echo Välj din senaste ATL_AkerSync_*_v03.csv i filrutan som öppnas.
echo ATL-filen läses bara lokalt och läggs inte i Git.
echo.
py -3 src\20_value_regression_v0a.py
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
  echo FEL: Value Regression avslutades med kod %RC%.
  echo Kopiera hela feltexten och skicka den till ChatGPT.
) else (
  echo KLART.
  echo Resultat: data\derived\value_regression_v0a\
  echo Skicka report.txt och model_comparison.csv till ChatGPT.
)
echo.
pause
exit /b %RC%
