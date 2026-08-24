@echo off
setlocal
cd /d "%~dp0"

echo ==============================================================================
echo AkerPass MVP v1.1 - release-QA
echo ==============================================================================

py -3 -m unittest tests.test_akerpass_v1 tests.test_prepare_akerdrift_hybrid_visual_qa tests.test_akerdrift_fast_v2_core tests.test_apply_akerdrift_fast_v2 -v
if errorlevel 1 goto :fail

call BUILD_AKERPASS_WEB_V1.bat
if errorlevel 1 goto :fail

py -3 src\43_verify_akerpass_web_v1.py
if errorlevel 1 goto :fail

echo.
echo AUTOMATISK RELEASE-QA: OK
echo Gor nu den manuella kartkontrollen i AKERPASS_MVP_V1_1_FREEZE.md.
echo Tagga inte releasen forran aven den ar godkand.
exit /b 0

:fail
echo.
echo RELEASE-QA: FEL
echo AkerPass MVP v1.1 far inte taggas.
exit /b 1
