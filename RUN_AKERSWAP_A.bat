@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================================
echo ÅkerSwap A - Sjöbo substitutions-feasibility
echo ================================================================

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 tools\akerswap_a_sjobo_feasibility_v0a.py
) else (
  python tools\akerswap_a_sjobo_feasibility_v0a.py
)

set RC=%ERRORLEVEL%
echo.
echo Return code: %RC%
echo Resultat: C:\AkerSync-AkerAccess\work\akerswap_a_sjobo_v0a\STOPPUNKT_A.md
echo.
exit /b %RC%
