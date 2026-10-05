@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================================
echo ÅkerSwap B1+B2+B3 - falsifieringssprint
echo ================================================================

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 tools\akerswap_b123_sjobo_v0a.py
) else (
  python tools\akerswap_b123_sjobo_v0a.py
)

set RC=%ERRORLEVEL%
echo.
echo Return code: %RC%
echo Resultat: %~dp0work\akerswap_b123_sjobo_v0a\STOPPUNKT_B123.md
echo.
exit /b %RC%
