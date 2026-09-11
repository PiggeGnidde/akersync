@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)

if not exist "config\akerpuls_split_fusion_qa_v1.json" (echo FAIL: freeze config missing.& exit /b 1)
if not exist "docs\AKERPULS_SPLIT_FUSION_QA_V1_FREEZE.md" (echo FAIL: freeze document missing.& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (echo FAIL: frozen pre-C7 fusion artifact missing.& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation\c7c_summary.json" (echo FAIL: C7C summary missing.& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7d_blind_fusion_qa\c7d_summary.json" (echo FAIL: C7D summary missing.& exit /b 1)

 echo ========================================================================================
 echo AkerPuls - SPLIT FUSION QA V1 FORMAL FREEZE VERIFICATION - ZERO PU
 echo ========================================================================================

py -3 -m unittest tests.test_akerpuls_split_fusion_qa_v1 -v
if errorlevel 1 exit /b 1

py -3 src\137_verify_akerpuls_split_fusion_qa_v1.py
if errorlevel 1 exit /b 1

endlocal
