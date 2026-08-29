@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "TAG=akerpass-akerminne-context-v1.0"
set "BRANCH=feature/akerprestation-web-phase0-v0a"
set "PHASE0_TAG=akerprestation-phase0-v0a"
set "PHASE0_SHA=c36bdeea304f6e9254d2f8d57a71b73d2898bb40"
set "AKERMINNE_TAG=akerminne-v1.0"
set "AKERMINNE_SHA=4b53ab24e9822f1c36c6cc31931dba3c1855fead"

echo ================================================================================================
echo FREEZE: AkerPass + AkerMinne + historisk jordbruksklass 1-10 + SKO
echo Tag: %TAG%
echo ================================================================================================
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if /I not "!CURRENT_BRANCH!"=="%BRANCH%" (
  echo FEL: fel branch. Aktuell: !CURRENT_BRANCH!
  echo Forvantad: %BRANCH%
  goto :fail
)

for /f "delims=" %%S in ('git status --porcelain') do (
  echo FEL: arbetsytan ar inte ren fore freeze.
  git status --short
  goto :fail
)

echo [1/7] Fetch origin + tags och verifiera pushad freeze-commit...
git fetch origin --tags
if errorlevel 1 goto :fail
for /f %%H in ('git rev-parse HEAD') do set "HEAD_SHA=%%H"
for /f %%H in ('git rev-parse origin/%BRANCH%') do set "REMOTE_SHA=%%H"
if /I not "!HEAD_SHA!"=="!REMOTE_SHA!" (
  echo FEL: lokal HEAD !HEAD_SHA! ar inte samma som origin/%BRANCH% !REMOTE_SHA!.
  goto :fail
)
echo Freeze commit ar pushad: !HEAD_SHA!

echo.
echo [2/7] Verifiera tidigare frysta baser...
for /f %%H in ('git rev-parse "%PHASE0_TAG%^{commit}"') do set "GOT_PHASE0=%%H"
if /I not "!GOT_PHASE0!"=="%PHASE0_SHA%" (
  echo FEL: %PHASE0_TAG% pekar pa !GOT_PHASE0!, vantat %PHASE0_SHA%.
  goto :fail
)
for /f %%H in ('git rev-parse "%AKERMINNE_TAG%^{commit}"') do set "GOT_AKM=%%H"
if /I not "!GOT_AKM!"=="%AKERMINNE_SHA%" (
  echo FEL: %AKERMINNE_TAG% pekar pa !GOT_AKM!, vantat %AKERMINNE_SHA%.
  goto :fail
)
git merge-base --is-ancestor %PHASE0_TAG% HEAD
if errorlevel 1 (
  echo FEL: %PHASE0_TAG% ar inte ancestor till freeze-committen.
  goto :fail
)
echo Bas-tags: PASS

echo.
echo [3/7] Verifiera exakt tillaten kodforandring sedan AkerPrestation phase 0 freeze...
set "ACTUAL=%TEMP%\akerpass_context_freeze_actual_%RANDOM%.txt"
set "EXPECTED=%TEMP%\akerpass_context_freeze_expected_%RANDOM%.txt"
git diff --name-only %PHASE0_TAG%..HEAD ^| sort > "!ACTUAL!"
(
  echo BUILD_AKERPASS_WEB_PHASE0.bat
  echo BUILD_AKERPASS_WEB_PHASE0_WORKTREE.bat
  echo FREEZE_AKERPASS_AKERMINNE_CONTEXT_V1.bat
  echo src/41b_enrich_akerpass_phase0_web.py
  echo src/42b_patch_akerpass_frontend_phase0.py
  echo src/43b_verify_akerpass_web_phase0.py
  echo src/68b_patch_akerpass_akerminne_reused_ui.py
  echo src/69b_verify_akerpass_akerminne_phase0_combined.py
  echo src/build_akerpass_web_phase0.py
  echo src/build_akerpass_web_phase0_worktree.py
  echo src/ensure_akerminne_recovery_local_config.py
  echo src/restore_orphaned_akerminne_web_payload.py
  echo tests/test_akerpass_web_phase0.py
  echo tests/test_akerpass_web_phase0_orphan_restore.py
  echo tests/test_akerpass_web_phase0_recovery.py
  echo tests/test_akerpass_web_phase0_worktree.py
) | sort > "!EXPECTED!"
fc /L "!EXPECTED!" "!ACTUAL!" >nul
if errorlevel 1 (
  echo FEL: diffen mot %PHASE0_TAG% innehaller annat an den godkanda WEB/context-allowlisten.
  echo --- Actual ---
  type "!ACTUAL!"
  echo --- Expected ---
  type "!EXPECTED!"
  del /q "!ACTUAL!" "!EXPECTED!" >nul 2>&1
  goto :fail
)
del /q "!ACTUAL!" "!EXPECTED!" >nul 2>&1
echo Kodscope: PASS - inga befintliga AkerScore/AkerVarde/AkerDrift-modellfiler andrade.

echo.
echo [4/7] WEB/context regression tests...
where py >nul 2>nul
if errorlevel 1 (
  python -m unittest discover -s tests -p "test_akerpass_web_phase0*.py" -v
) else (
  py -3 -m unittest discover -s tests -p "test_akerpass_web_phase0*.py" -v
)
if errorlevel 1 goto :fail

echo.
echo [5/7] Slutlig data/UI-verifiering...
where py >nul 2>nul
if errorlevel 1 (
  python src\43b_verify_akerpass_web_phase0.py
  if errorlevel 1 goto :fail
  python src\69b_verify_akerpass_akerminne_phase0_combined.py
) else (
  py -3 src\43b_verify_akerpass_web_phase0.py
  if errorlevel 1 goto :fail
  py -3 src\69b_verify_akerpass_akerminne_phase0_combined.py
)
if errorlevel 1 goto :fail

for /f "delims=" %%S in ('git status --porcelain') do (
  echo FEL: arbetsytan blev oren under verifieringen.
  git status --short
  goto :fail
)

echo.
echo [6/7] Skapa/verifiera annoterad tagg %TAG%...
git rev-parse -q --verify "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 (
  for /f %%H in ('git rev-list -n 1 "%TAG%"') do set "TAG_SHA=%%H"
  if /I not "!TAG_SHA!"=="!HEAD_SHA!" (
    echo FEL: taggen %TAG% finns redan men pekar pa !TAG_SHA!, inte !HEAD_SHA!.
    echo Taggen flyttas INTE.
    goto :fail
  )
  echo Taggen finns redan korrekt pa !HEAD_SHA!.
) else (
  git tag -a "%TAG%" -m "Freeze AkerPass + AkerMinne + context v1.0 - 33 municipalities - 128636 fields - 1414996 AkerMinne field-years - historic agricultural class 1-10 - 18 SKO source IDs / 17 dominant field IDs - no AkerScore/AkerVarde/AkerDrift recalibration"
  if errorlevel 1 goto :fail
)

echo.
echo [7/7] Pusha annoterad tagg och verifiera ren arbetsyta...
git push origin "refs/tags/%TAG%"
if errorlevel 1 goto :fail
git ls-remote --exit-code --tags origin "refs/tags/%TAG%" >nul
if errorlevel 1 (
  echo FEL: remote tag kunde inte verifieras efter push.
  goto :fail
)
for /f "delims=" %%S in ('git status --porcelain') do (
  echo FEL: arbetsytan ar inte ren efter taggning.
  git status --short
  goto :fail
)

echo.
echo ================================================================================================
echo AKERPASS + AKERMINNE + CONTEXT V1.0 FREEZE: PASS
echo ================================================================================================
echo Tag: %TAG%
echo Commit: !HEAD_SHA!
echo Branch: %BRANCH%
echo AkerPrestation context base: %PHASE0_TAG% @ %PHASE0_SHA%
echo AkerMinne base: %AKERMINNE_TAG% @ %AKERMINNE_SHA%
echo Tests: WEB/context unittest + phase0 verifier + combined 33-municipality verifier PASS
echo Scope: AkerPass + AkerMinne 2015-2025 + historisk jordbruksklass 1-10 + SKO
echo Counts: 33 kommuner / 128636 skiften / 1414996 skifte-ar / 18 SKO source / 17 dominant
 echo Working tree: CLEAN
 echo Remote commit: VERIFIED on origin/%BRANCH%
 echo Annotated tag: PUSHED and remote-visible
 echo.
git show --no-patch --decorate "%TAG%"
echo.
echo STOPPUNKT E - combined context freeze complete.
pause
exit /b 0

:fail
echo.
echo ================================================================================================
echo AKERPASS + AKERMINNE + CONTEXT V1.0 FREEZE: FAIL
 echo ================================================================================================
echo Ingen befintlig tagg flyttas eller tvingas.
echo Kopiera hela konsoltexten till kodchatten.
pause
exit /b 1
