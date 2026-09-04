@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo TEST CANDIDATE V3 - not approved for production. Full tests must pass here first.
echo [1/2] Full offline regression and scene-order candidate safety tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery tests.test_rapskartan_s2_pilot tests.test_rapskartan_model_dataset tests.test_rapskartan_model_training tests.test_rapskartan_2025_blind_prediction tests.test_rapskartan_2025_blind_evaluation tests.test_rapskartan_map_product tests.test_rapskartan_parity_diagnostic tests.test_rapskartan_pixel_cases tests.test_rapskartan_pixel_reference tests.test_rapskartan_local_candidate tests.test_rapskartan_scene_choices tests.test_rapskartan_scene_order_candidate -q >nul
if errorlevel 1 exit /b 1
echo [2/2] Offline candidate: at most two dates recomputed; unchanged V2 checkpoints reused.
echo Existing scene assets are still hash-checked. No login or downloads. No map product.
py -3 -u src\102_diagnose_rapskartan_2025_parity.py --engine-profile reference_scene_order_v3 --output-dir data\derived\rapskartan_v1\2025_candidate_parity_v3 %*
exit /b %ERRORLEVEL%
