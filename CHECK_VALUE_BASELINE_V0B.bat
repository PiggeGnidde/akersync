@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================
echo AkerSync Value Regression v0b - baseline-only sanity check
echo ============================================================================
echo.
py -3 src\20b_value_regression_v0b.py --baseline-only
if errorlevel 1 (
  echo.
  echo CHECK MISSLYCKADES. Skicka hela texten till ChatGPT.
) else (
  echo.
  echo CHECK KLAR.
)
pause
