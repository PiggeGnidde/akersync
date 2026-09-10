@echo off
setlocal
cd /d %~dp0

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C5D BLIND THIRD-HOLDOUT QA - ZERO PU
echo ========================================================================================

python -m unittest -v tests.test_akerpuls_prelim_fields_2026_c5d_contract
if errorlevel 1 exit /b 1

python src\128_akerpuls_prelim_fields_2026_c5d_blind_qa.py
if errorlevel 1 exit /b 1

endlocal
