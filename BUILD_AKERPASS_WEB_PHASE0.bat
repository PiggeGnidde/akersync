@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================================================
echo AkerPass WEB FAS 0 - historisk jordbruksklass 1-10 + SKO i Historik / referens
echo ========================================================================================
echo.

if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas.
  pause
  exit /b 1
)

if not exist "data\derived\akerprestation_phase0\skane\field_static_context.parquet" (
  echo FEL: fryst AkerPrestation fas 0-context saknas lokalt.
  echo Forvantad fil:
  echo   data\derived\akerprestation_phase0\skane\field_static_context.parquet
  echo Bygg inte om eller imputera har - aterstall den validerade fas 0-builden forst.
  pause
  exit /b 1
)

if not exist "data\derived\geometry_payload.json" (
  echo FEL: geometry_payload.json saknas. Kor befintligt Skane-databygge forst.
  pause
  exit /b 1
)

if not exist "data\derived\akerscore_soil_v0c\akerscore_soil_skiften.csv" (
  echo FEL: fryst AkerScore v0c-output saknas.
  pause
  exit /b 1
)

if not exist "data\derived\akervarde_v1_0_rc1_freeze\model_coefficients.csv" (
  echo FEL: fryst AkerVarde-artifact saknas.
  pause
  exit /b 1
)

if not exist "data\derived\akerdrift_fast_v2_hybrid_rc1\akerdrift_fast_v2_hybrid_rc1_skane.parquet" (
  echo FEL: AkerDrift Fast V2 Hybrid RC1-output saknas.
  pause
  exit /b 1
)

echo [1/2] WEB FAS 0 regression tests...
where py >nul 2>nul
if errorlevel 1 (
  python -m pytest -q tests\test_akerpass_web_phase0.py
) else (
  py -3 -m pytest -q tests\test_akerpass_web_phase0.py
)
if errorlevel 1 goto :error

echo.
echo [2/2] Build + legacy QA + phase0 enrichment + phase0 QA...
where py >nul 2>nul
if errorlevel 1 (
  python src\build_akerpass_web_phase0.py
) else (
  py -3 src\build_akerpass_web_phase0.py
)
if errorlevel 1 goto :error

echo.
echo ================================================================================
echo WEB FAS 0 RUNNER: PASS
echo ================================================================================
echo Lokal fil: dist\index.html
echo Starta med START_AKERPASS_LOCAL.bat och kontrollera Historik / referens.
echo.
pause
exit /b 0

:error
echo.
echo WEB FAS 0 RUNNER: FAIL
echo Kopiera hela konsoltexten till kodchatten.
pause
exit /b 1
