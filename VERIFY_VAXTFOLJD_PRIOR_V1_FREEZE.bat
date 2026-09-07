@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ========================================================================================
echo AkerPuls Vaxtfoljdsprior V1 - local freeze verifier
echo ========================================================================================
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 2
)

if "%~1"=="" (
  py -3 analysis\vaxfoljd_prior_v1\verify_vaxfoljd_prior_v1_freeze.py
) else (
  py -3 analysis\vaxfoljd_prior_v1\verify_vaxfoljd_prior_v1_freeze.py "%~1"
)
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%

echo VERIFY_VAXTFOLJD_PRIOR_V1_FREEZE: PASS
exit /b 0
