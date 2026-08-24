@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo AkerDrift Hybrid RC1: skapar avgransad visuell QA-lista.
py -3 src\48_prepare_akerdrift_hybrid_visual_qa.py
if errorlevel 1 goto :error

echo.
echo KLART. Oppna data\derived\akerdrift_fast_v2_hybrid_rc1\qa\visual_review.html
echo Starta kartan med START_AKERPASS_LOCAL.bat forst.
pause
exit /b 0

:error
echo.
echo FEL: visuell QA-lista kunde inte skapas.
pause
exit /b 1
