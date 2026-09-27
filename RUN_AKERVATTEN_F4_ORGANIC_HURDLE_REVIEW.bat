@echo off
cd /d %~dp0
py -3 -m unittest tests.test_akervatten_f4_organic_hurdle_review -v
if errorlevel 1 goto fail
py -3 src\103_akervatten_f4_organic_hurdle_review.py
if errorlevel 1 goto fail
echo RUN_AKERVATTEN_F4_ORGANIC_HURDLE_REVIEW: PASS
exit /b 0
:fail
echo RUN_AKERVATTEN_F4_ORGANIC_HURDLE_REVIEW: FAIL
exit /b 1
