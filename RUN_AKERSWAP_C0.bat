@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================================
echo ÅkerSwap C0 - real portfolio identifier audit
echo ================================================================

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 tools\akerswap_c0_real_portfolio_audit_v0a.py
) else (
  python tools\akerswap_c0_real_portfolio_audit_v0a.py
)

set RC=%ERRORLEVEL%
echo.
echo Return code: %RC%
echo Resultat: %~dp0work\akerswap_c0_real_portfolio_audit_v0a\STOPPUNKT_C0.md
echo.
exit /b %RC%
