@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================================================
echo AkerPass WEB FAS 0 - legacy AkerPass + AkerMinne 2015-2025 + klass 1-10 + SKO
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

echo [0/3] Recover validated orphaned AkerMinne web payload if available...
where py >nul 2>nul
if errorlevel 1 (
  python src\restore_orphaned_akerminne_web_payload.py
) else (
  py -3 src\restore_orphaned_akerminne_web_payload.py
)
set "ORPHAN_RC=%ERRORLEVEL%"
if "%ORPHAN_RC%"=="0" goto :tests
if not "%ORPHAN_RC%"=="2" goto :error

echo.
echo No orphaned AkerMinne payload was restored. Preparing normal frozen-recovery config...
where py >nul 2>nul
if errorlevel 1 (
  python src\ensure_akerminne_recovery_local_config.py
) else (
  py -3 src\ensure_akerminne_recovery_local_config.py
)
if errorlevel 1 goto :error

:tests
echo.
echo [1/3] Combined WEB regression tests - Python standard library unittest...
where py >nul 2>nul
if errorlevel 1 (
  python -m unittest discover -s tests -p "test_akerpass_web_phase0*.py" -v
) else (
  py -3 -m unittest discover -s tests -p "test_akerpass_web_phase0*.py" -v
)
if errorlevel 1 goto :error

echo.
echo [2/3] Discover/recover legacy + frozen AkerMinne artifacts, compose and verify...
where py >nul 2>nul
if errorlevel 1 (
  python src\build_akerpass_web_phase0_worktree.py
) else (
  py -3 src\build_akerpass_web_phase0_worktree.py
)
if errorlevel 1 goto :error

echo.
echo [3/3] Combined WEB FAS 0 completed and verified.
echo.
echo ================================================================================
echo COMBINED WEB FAS 0 WORKTREE RUNNER: PASS
echo ================================================================================
echo Lokal fil: dist\index.html
echo Starta med START_AKERPASS_LOCAL.bat.
echo Kontrollera bade AkerMinne 2015-2025 och Historik / referens med SKO.
echo.
pause
exit /b 0

:error
echo.
echo COMBINED WEB FAS 0 WORKTREE RUNNER: FAIL
echo Kopiera hela konsoltexten till kodchatten.
pause
exit /b 1
