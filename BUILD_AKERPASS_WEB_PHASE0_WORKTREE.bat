@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================================================
echo AkerPass WEB FAS 0 - worktree-aware legacy artifact reuse
echo ========================================================================================
echo.

if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas.
  pause
  exit /b 1
)

if not exist "data\derived\akerprestation_phase0\skane\field_static_context.parquet" (
  echo FEL: fryst AkerPrestation fas 0-context saknas i detta worktree.
  echo Forvantad fil:
  echo   data\derived\akerprestation_phase0\skane\field_static_context.parquet
  pause
  exit /b 1
)

echo [1/2] WEB FAS 0 regression tests - Python standard library unittest...
where py >nul 2>nul
if errorlevel 1 (
  python -m unittest discover -s tests -p "test_akerpass_web_phase0*.py" -v
) else (
  py -3 -m unittest discover -s tests -p "test_akerpass_web_phase0*.py" -v
)
if errorlevel 1 goto :error

echo.
echo [2/2] Discover legacy artifacts across Git worktrees + build + verify...
where py >nul 2>nul
if errorlevel 1 (
  python src\build_akerpass_web_phase0_worktree.py
) else (
  py -3 src\build_akerpass_web_phase0_worktree.py
)
if errorlevel 1 goto :error

echo.
echo ================================================================================
echo WEB FAS 0 WORKTREE RUNNER: PASS
echo ================================================================================
echo Lokal fil: dist\index.html
echo Starta med START_AKERPASS_LOCAL.bat och kontrollera Historik / referens.
echo.
pause
exit /b 0

:error
echo.
echo WEB FAS 0 WORKTREE RUNNER: FAIL
echo Kopiera hela konsoltexten till kodchatten.
pause
exit /b 1
