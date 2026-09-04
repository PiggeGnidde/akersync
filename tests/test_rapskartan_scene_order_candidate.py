from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rapskartan_map_product_core import aggregate_local_scene_timeseries, sha256_bytes, sha256_file, stable_json
from rapskartan_parity_diagnostic_core import read_table, save_table, save_day_checkpoint
from rapskartan_scene_order_candidate import PROFILE, ordered_metadata, order_report, prepare_reuse, reuse_day


def scene(day, item, cloud):
    return {'acquisition_date': day, 'item_id': item, 'cloud_cover': cloud}


class SceneOrderCandidateTests(unittest.TestCase):
    def test_truncation_not_rounding_and_no_input_mutation(self):
        scenes = [scene('2025-05-20', 'B', .007034), scene('2025-05-20', 'A', .007326),
                  scene('2025-05-20', 'C', 17.019999)]
        original = copy.deepcopy(scenes)
        adapted = ordered_metadata(scenes)
        self.assertEqual([s['cloud_cover'] for s in adapted], [0., 0., 17.01])
        self.assertEqual(scenes, original)
        report, changed = order_report(scenes)
        self.assertEqual(changed, ['2025-05-20'])
        self.assertEqual(report.sort_values('rank_v3').item_id.tolist(), ['A', 'B', 'C'])
        for value in (float('nan'), float('inf'), -1, 101):
            with self.assertRaisesRegex(RuntimeError, 'cloud'):
                ordered_metadata([scene('2025-05-20', 'A', value)])

    def test_general_rule_not_satellite_or_date_hardcoding(self):
        # This synthetic date has no tie after truncation, so lower-cloud B wins.
        scenes = [scene('2025-04-25', 'A', 17.506027), scene('2025-04-25', 'B', 17.012271)]
        report, changed = order_report(scenes)
        self.assertEqual(changed, [])
        self.assertEqual(report.sort_values('rank_v3').item_id.tolist(), ['B', 'A'])

    def test_real_pixels_change_only_by_source_choice(self):
        from tests.test_rapskartan_pixel_cases import fixture
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)
            contract, fields, scenes = fixture(archive)
            for s in scenes:
                s['acquisition_date'] = '2025-05-20'
            scenes[0]['cloud_cover'], scenes[1]['cloud_cover'] = .007326, .007034
            original = copy.deepcopy(scenes)
            kwargs = {'engine_profile': 'reference_pixels_v2'}
            before = aggregate_local_scene_timeseries(fields, scenes, archive, contract, **kwargs)
            after = aggregate_local_scene_timeseries(fields, ordered_metadata(scenes), archive, contract, **kwargs)
            a = aggregate_local_scene_timeseries(fields, [scenes[0]], archive, contract, **kwargs)
            b = aggregate_local_scene_timeseries(fields, [scenes[1]], archive, contract, **kwargs)
            pd.testing.assert_frame_equal(before, b)
            pd.testing.assert_frame_equal(after, a)
            self.assertNotEqual(before.iloc[0].B02_p50, after.iloc[0].B02_p50)
            self.assertEqual(scenes, original)

    def source_fixture(self, source):
        source.mkdir()
        days = ['2025-03-21', '2025-04-20', '2025-05-20']
        scenes = [scene(d, d+'-A', .007326) for d in days] + [scene(d, d+'-B', .007034) for d in (days[0], days[2])]
        previous = {'engine_profile': 'reference_pixels_v2', 'scene_inventory_sha256': 'inventory',
                    'prediction_lock_sha256': 'predictions', 'model_manifest_sha256': 'models',
                    'field_ids': ['f'], 'runtime': {'python': 'test'}}
        identity = sha256_bytes(stable_json(previous).encode())
        summary = {'diagnostic_id': identity, 'observations_local': 3, 'acquisition_dates': 3,
                   'reference_feature_replay_vs_locked': {'status': 'PASS'},
                   'reference_timeseries_replay_vs_locked': {'status': 'PASS'}}
        (source / 'diagnostic_summary.json').write_text(json.dumps(summary))
        (source / 'diagnostic_manifest.json').write_text('{}')
        frame = pd.DataFrame({'development_field_id': ['f']*3, 'acquisition_date': days,
                              'x': [.12345678901234567, float('nan'), .2]})
        save_table(source / 'local_timeseries.csv', frame)
        for day in days:
            save_day_checkpoint(source / 'checkpoints', day, identity, frame[frame.acquisition_date.eq(day)])
        return previous, scenes, frame

    def test_reuse_identity_scope_and_runtime_are_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'v2'
            previous, scenes, frame = self.source_fixture(source)
            with patch('rapskartan_scene_order_candidate.verify_source', return_value=previous):
                reuse = prepare_reuse(source, ROOT, previous, scenes)
                self.assertEqual(reuse['changed_dates'], ['2025-03-21', '2025-05-20'])
                self.assertEqual(reuse['provenance']['unchanged_dates'], ['2025-04-20'])
                pd.testing.assert_frame_equal(reuse_day(reuse, '2025-04-20'), frame.iloc[1:2].reset_index(drop=True))
                for name in ('runtime', 'field_ids', 'scene_inventory_sha256', 'model_manifest_sha256', 'prediction_lock_sha256'):
                    altered = {**previous, name: 'changed'}
                    with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                        prepare_reuse(source, ROOT, altered, scenes)
                with self.assertRaisesRegex(RuntimeError, 'outside'):
                    prepare_reuse(source, ROOT, previous, scenes + [scene('2025-04-20', '2025-04-20-B', .007034)])
                with self.assertRaisesRegex(RuntimeError, 'scope'):
                    prepare_reuse(source, ROOT, previous, scenes[:2])

    def test_reuse_changed_missing_and_inconsistent_checkpoints_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'v2'
            previous, scenes, frame = self.source_fixture(source)
            with patch('rapskartan_scene_order_candidate.verify_source', return_value=previous):
                reuse = prepare_reuse(source, ROOT, previous, scenes)
            with self.assertRaisesRegex(RuntimeError, 'ordering changed'):
                reuse_day(reuse, '2025-05-20')
            day = '2025-04-20'
            # A self-consistent checkpoint manifest must still match the source CSV.
            bad = frame[frame.acquisition_date.eq(day)].copy(); bad['x'] = 99.
            save_day_checkpoint(source / 'checkpoints', day, reuse['identity'], bad)
            with self.assertRaisesRegex(RuntimeError, 'disagrees'):
                reuse_day(reuse, day)
            with patch('rapskartan_scene_order_candidate.read_day_checkpoint', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'missing'):
                    reuse_day(reuse, day)

    def test_reference_failure_and_identity_corruption_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'v2'
            previous, scenes, _ = self.source_fixture(source)
            path = source / 'diagnostic_summary.json'
            summary = json.loads(path.read_text())
            with patch('rapskartan_scene_order_candidate.verify_source', return_value=previous):
                summary['reference_feature_replay_vs_locked']['status'] = 'FAIL'
                path.write_text(json.dumps(summary))
                with self.assertRaisesRegex(RuntimeError, 'reference replay'):
                    prepare_reuse(source, ROOT, previous, scenes)
                summary['reference_feature_replay_vs_locked']['status'] = 'PASS'
                summary['diagnostic_id'] = 'wrong'
                path.write_text(json.dumps(summary))
                with self.assertRaisesRegex(RuntimeError, 'identity is inconsistent'):
                    prepare_reuse(source, ROOT, previous, scenes)

    def test_runner_defaults_production_and_windows_command(self):
        import inspect
        self.assertEqual(inspect.signature(aggregate_local_scene_timeseries).parameters['engine_profile'].default, 'original')
        production = (ROOT / 'src/100_generate_rapskartan_2025_map_product.py').read_text()
        self.assertNotIn(PROFILE, production)
        bat = (ROOT / 'RUN_RAPSKARTAN_SCENE_ORDER_CANDIDATE.bat').read_text()
        self.assertIn('--engine-profile reference_scene_order_v3', bat)
        self.assertIn('2025_candidate_parity_v3', bat)
        self.assertNotIn('powershell', bat.lower())

    def test_full_runner_reuses_only_unchanged_dates_and_restarts(self):
        from shapely.geometry import box
        spec = importlib.util.spec_from_file_location('v3_diagnostic', ROOT / 'src/102_diagnose_rapskartan_2025_parity.py')
        runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, stop_c, stop_d, product, archive, base = [root / n for n in ('v2', 'c', 'd', 'product', 'archive', 'v3')]
            previous, scenes, _ = self.source_fixture(source)
            for folder in (stop_c, stop_d, product / 'source', archive, base):
                folder.mkdir(parents=True)
            days = sorted({s['acquisition_date'] for s in scenes})
            selection = pd.DataFrame({'development_field_id': ['f'], 'municipality_code': ['1262']})
            ts = pd.DataFrame({'development_field_id': ['f']*3, 'acquisition_date': days,
                'data_quality_status': ['VALID']*3, 'sample_pixels': [4]*3, 'valid_pixels': [4]*3,
                'valid_pixel_fraction': [1.]*3,
                **{f'{name}_p{p}': [.1]*3 for name in runner.SPECTRAL_NAMES for p in (10, 50, 90)}})
            features = pd.DataFrame({'development_field_id': ['f']*3, 'cutoff_date': days, 'x': [.1]*3})
            predictions = pd.DataFrame({'development_field_id': ['f']*3, 'cutoff_date': days,
                'model_arm': ['SATELLITE_ONLY']*3, 'data_quality_status': ['USABLE']*3,
                'raw_probability': [.1]*3, 'calibrated_probability': [.1]*3, 'predicted_at_frozen_p95': [False]*3})
            failed = predictions.copy()
            failed.loc[0, ['raw_probability', 'calibrated_probability']] = .9
            failed.loc[0, 'predicted_at_frozen_p95'] = True
            for name, frame in {'blind_field_selection.csv': selection, 'blind_predictions_locked.csv': predictions,
                'blind_prior_features.csv': selection, 'blind_s2_timeseries.csv': ts, 'blind_temporal_features.csv': features,
                'blind_selection_geometry_wkb.csv': pd.DataFrame({'development_field_id': ['f'], 'geometry_wkb_hex': [box(0, 0, 20, 20).wkb_hex]})}.items():
                save_table(stop_d / name, frame)
            for path in (stop_c / 'model_artifacts_manifest.json', stop_d / 'prediction_lock_manifest.json', product / 'source/scene_inventory.json'):
                path.write_text('{}')
            previous.update(scene_inventory_sha256=sha256_file(product / 'source/scene_inventory.json'),
                            prediction_lock_sha256=sha256_file(stop_d / 'prediction_lock_manifest.json'),
                            model_manifest_sha256=sha256_file(stop_c / 'model_artifacts_manifest.json'))
            identity = sha256_bytes(stable_json(previous).encode())
            summary = json.loads((source / 'diagnostic_summary.json').read_text()); summary['diagnostic_id'] = identity
            (source / 'diagnostic_summary.json').write_text(json.dumps(summary))
            save_table(source / 'local_timeseries.csv', ts)
            for day in days:
                save_day_checkpoint(source / 'checkpoints', day, identity, ts[ts.acquisition_date.eq(day)])
            source_hashes = {str(p.relative_to(source)): sha256_file(p) for p in source.rglob('*') if p.is_file()}
            args = Namespace(stop_c_dir=stop_c, stop_d_dir=stop_d, product_dir=product, scene_archive=archive,
                             engine_profile=PROFILE, reuse_diagnostic_dir=source)
            snapshot = {'branch': runner.FEATURE_BRANCH, 'working_tree_clean': True, 'head_tree': 'tree', 'head': 'head'}
            frozen = {'model_version': 'test', 'frozen_feature_contract_version': 'test',
                      'frozen_model_contract_id': 'test', 'frozen_feature_contract': {}}
            original_scenes = copy.deepcopy(scenes)
            def aggregate(fields, day_scenes, archive, contract, **kwargs):
                self.assertEqual(kwargs['engine_profile'], 'reference_pixels_v2')
                self.assertTrue(all(s['cloud_cover'] == 0 for s in day_scenes))
                return ts[ts.acquisition_date.eq(day_scenes[0]['acquisition_date'])].copy()
            with contextlib.ExitStack() as stack:
                for name, value in {'repository_snapshot': snapshot, 'verify_stop_c': None, 'verify_stop_d': None,
                    'frozen_runtime_contract': frozen, 'select_parity_field_ids': ['f'], 'runtime_versions': previous['runtime'],
                    'validate_scenes': scenes, 'verify_day_assets': [], 'temporal_feature_columns': ['x'],
                    'build_blind_temporal_features': features}.items():
                    stack.enter_context(patch.object(runner, name, return_value=value))
                stack.enter_context(patch('rapskartan_scene_order_candidate.verify_source', return_value=previous))
                process = stack.enter_context(patch.object(runner, 'aggregate_local_scene_timeseries', side_effect=aggregate))
                predict = stack.enter_context(patch.object(runner, 'make_predictions', side_effect=[predictions, predictions, failed]*2))
                out = runner.run(args, base)
                self.assertEqual(process.call_count, 2)
                self.assertEqual(read_table(out / 'date_progress.csv')['mode'].tolist(), ['computed', 'reused_v2_verified', 'computed'])
                result = json.loads((out / 'diagnostic_summary.json').read_text())
                self.assertEqual(result['engine_profile'], PROFILE)
                self.assertEqual(result['local_engine_vs_locked']['status'], 'FAIL')
                self.assertFalse(result['scope']['full_map_generated'])
                self.assertEqual(runner.run(args, base), out)
                self.assertEqual(process.call_count, 2)
                self.assertEqual(predict.call_count, 6)
                self.assertEqual(read_table(out / 'date_progress.csv')['mode'].tolist(), ['checkpoint']*3)
            self.assertEqual(scenes, original_scenes)
            self.assertEqual(source_hashes, {str(p.relative_to(source)): sha256_file(p) for p in source.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
