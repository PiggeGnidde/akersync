@echo off
cd /d %~dp0
py -3 src\106_akervatten_g2_review.py
if errorlevel 1 exit /b 1
