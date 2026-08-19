@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Ferrari terrain contrast · v0e
echo ================================================================================
echo.
echo A: Vollsjo super-Ferrari vs Bjarred/Lomma extreme non-Ferrari + lokala kontroller.
echo B: global kontrast super-Ferrari utanfor klass 10 vs extreme non-Ferrari i klass 10.
echo Jord/Ferrari-urvalet ar LAST fran v0c/v0d. Nu laggs topografi och ev. befintlig TWI pa.
echo.
py -3 src\30e_ferrari_terrain_contrast_v0e.py
if errorlevel 1 (
  echo.
  echo FEL: v0e avbrot. Kopiera hela texten till ChatGPT.
  pause
  exit /b 1
)
echo.
echo KLART. Output: data\derived\agri_class5_10_v0e_terrain_contrast\
echo.
echo Skicka helst:
echo   report.txt
echo   A_vollsjo_bjarred_summary.csv
echo   A_vollsjo_vs_bjarred_contrast.csv
echo   B_global_anomaly_summary.csv
echo   B_global_contrast.csv
echo.
echo Oppna ocksa A_vollsjo_bjarred_map.html for visuell QA.
pause
