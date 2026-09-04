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
from unittest.mock import patch, Mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import rapskartan_adopted_engine as adopted
from rapskartan_map_product_core import sha256_file, sha256_bytes, stable_json, load_map_contract
from rapskartan_parity_diagnostic_core import save_table, save_day_checkpoint, read_table
from rapskartan_s2_pilot_core import artifact_records, write_json


def load_script(name):
    spec = importlib.util.spec_from_file_location('test_' + name[:3], ROOT / 'src' / name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class AdoptedEngineTests(unittest.TestCase):
    def evidence_fixture(self, root):
        source, stop_c, stop_d = [root / n for n in ('source', 'stop_c', 'stop_d')]
        for folder in (source, stop_c, stop_d, root / 'analysis/rapskartan_v1', root / 'src'):
            folder.mkdir(parents=True, exist_ok=True)
        scene_file = root / 'inventory.json'; scene_file.write_text('{}')
        (stop_c / 'model_artifacts_manifest.json').write_text('{}')
        (stop_d / 'prediction_lock_manifest.json').write_text('{}')
        for name in adopted.PIXEL_CODE:
            (root / name).write_bytes(b'pixel code\n')
        inputs = {'field_ids': ['f'], 'runtime': {'test': True},
                  'scene_inventory_sha256': sha256_file(scene_file),
                  'model_manifest_sha256': sha256_file(stop_c / 'model_artifacts_manifest.json'),
                  'prediction_lock_sha256': sha256_file(stop_d / 'prediction_lock_manifest.json')}
        identity = sha256_bytes(stable_json(inputs).encode())
        summary = {'repository_head': 'a'*40, 'diagnostic_id': identity, 'engine_profile': adopted.PROFILE,
                   'scene_order_candidate': {'scene_order_policy': adopted.POLICY},
                   'fields': 1, 'acquisition_dates': 1, 'observations_local': 1,
                   **{name: {'status': 'PASS', 'rows': 1} for name in
                      ('local_engine_vs_locked', 'reference_feature_replay_vs_locked', 'reference_timeseries_replay_vs_locked')}}
        write_json(source / 'diagnostic_inputs.json', inputs); write_json(source / 'diagnostic_summary.json', summary)
        frame = pd.DataFrame({'development_field_id': ['f'], 'acquisition_date': ['2025-03-21'],
                              'value': [.12345678901234567], 'empty': [None]})
        save_table(source / 'local_timeseries.csv', frame)
        save_day_checkpoint(source / 'checkpoints', '2025-03-21', identity, frame)
        write_json(source / 'diagnostic_manifest.json', {'status': 'DIAGNOSTICS_COMPLETE',
                   'artifacts': artifact_records(source, ['diagnostic_inputs.json', 'diagnostic_summary.json', 'local_timeseries.csv'])})
        receipt = {'repository_head': 'a'*40, 'diagnostic_id': identity, 'engine_profile': adopted.PROFILE,
                   'diagnostic_manifest_sha256': sha256_file(source / 'diagnostic_manifest.json'),
                   'fields': 1, 'decisions': 1, 'acquisition_dates': 1, 'observations': 1}
        write_json(root / adopted.ACCEPTANCE_REL, receipt)
        return source, stop_c, stop_d, scene_file, inputs, frame

    def test_evidence_hash_runtime_code_and_scope_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, c, d, scene_file, inputs, _ = self.evidence_fixture(root)
            args = (source, root, c, d, scene_file, ['f'])
            with patch.object(adopted, 'runtime_versions', return_value={'test': True}), patch.object(adopted.subprocess, 'run', return_value=Mock(stdout=b'pixel code\r\n')):
                receipt, verified, manifest = adopted.verify_evidence(*args)
                self.assertEqual(verified, inputs)
                with self.assertRaisesRegex(RuntimeError, 'field_ids'):
                    adopted.verify_evidence(source, root, c, d, scene_file, ['other'])
                with patch.object(adopted, 'runtime_versions', return_value={'test': False}):
                    with self.assertRaisesRegex(RuntimeError, 'runtime'):
                        adopted.verify_evidence(*args)
                with patch.object(adopted.subprocess, 'run', return_value=Mock(stdout=b'changed')):
                    with self.assertRaisesRegex(RuntimeError, 'code changed'):
                        adopted.verify_evidence(*args)
                (source / 'local_timeseries.csv').write_text('changed')
                with self.assertRaisesRegex(RuntimeError, 'artifact differs'):
                    adopted.verify_evidence(*args)
                (source / 'diagnostic_manifest.json').write_text('{}')
                with self.assertRaisesRegex(RuntimeError, 'manifest differs'):
                    adopted.verify_evidence(*args)

    def test_exact_parquet_replay_and_missing_checkpoint_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, _, _, _, inputs, expected = self.evidence_fixture(Path(temporary))
            pd.testing.assert_frame_equal(adopted.replay_timeseries(source, inputs), expected)
            with patch.object(adopted, 'read_day_checkpoint', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'checkpoint missing'):
                    adopted.replay_timeseries(source, inputs)
            bad = expected.copy(); bad['value'] = .9
            with patch.object(adopted, 'read_day_checkpoint', return_value=bad):
                with self.assertRaisesRegex(RuntimeError, 'does not match'):
                    adopted.replay_timeseries(source, inputs)

    def test_real_raster_daily_restart_is_exact_v3(self):
        from tests.test_rapskartan_pixel_cases import fixture
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); contract, fields, scenes = fixture(root / 'archive')
            for scene in scenes: scene['acquisition_date'] = '2025-05-20'
            scenes[0]['cloud_cover'], scenes[1]['cloud_cover'] = .007326, .007034
            expected = adopted.aggregate_local_scene_timeseries(fields, [scenes[0]], root / 'archive', contract, engine_profile='reference_pixels_v2')
            frame = adopted.aggregate_adopted(fields, scenes, root / 'archive', contract, root / 'days', 'identity', progress_prefix='TEST')
            pd.testing.assert_frame_equal(frame, expected)
            with patch.object(adopted, 'aggregate_local_scene_timeseries', side_effect=AssertionError('should reuse')):
                again = adopted.aggregate_adopted(fields, scenes, root / 'archive', contract, root / 'days', 'identity', progress_prefix='TEST')
                pd.testing.assert_frame_equal(again, expected)
            with self.assertRaisesRegex(RuntimeError, 'checkpoint mismatch'):
                adopted.aggregate_adopted(fields, scenes, root / 'archive', contract, root / 'days', 'old-engine', progress_prefix='TEST')

    def test_no_coverage_date_is_checkpointed_but_other_errors_propagate(self):
        fields = pd.DataFrame({'development_field_id': ['f']})
        scenes = [{'acquisition_date': day, 'item_id': day, 'cloud_cover': 0.} for day in ('2025-03-21', '2025-05-20')]
        frame = pd.DataFrame({'development_field_id': ['f'], 'acquisition_date': ['2025-05-20']})
        empty = RuntimeError('Local Sentinel-2 scene aggregation produced no field observations')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(adopted, 'aggregate_local_scene_timeseries', side_effect=[empty, frame]):
                result = adopted.aggregate_adopted(fields, scenes, root, {}, root / 'days', 'id', progress_prefix='TEST')
                pd.testing.assert_frame_equal(result, frame)
            with patch.object(adopted, 'aggregate_local_scene_timeseries', side_effect=AssertionError('no recomputation')):
                adopted.aggregate_adopted(fields, scenes, root, {}, root / 'days', 'id', progress_prefix='TEST')
            with patch.object(adopted, 'aggregate_local_scene_timeseries', side_effect=RuntimeError('damaged raster')):
                with self.assertRaisesRegex(RuntimeError, 'damaged raster'):
                    adopted.aggregate_adopted(fields, scenes, root, {}, root / 'other', 'id', progress_prefix='TEST')

    def test_municipality_checkpoint_binds_prior_provenance(self):
        runner = load_script('100_generate_rapskartan_2025_map_product.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root / 'code.parquet'; prior = root / 'prior.csv'
            self.assertIsNone(runner.read_checkpoint(path, path.with_suffix('.json'), 'id', prior))
            prior.write_text('original'); frame = pd.DataFrame({'field_id': ['f']})
            runner.write_checkpoint(path, frame, 'id', prior)
            pd.testing.assert_frame_equal(runner.read_checkpoint(path, path.with_suffix('.json'), 'id', prior), frame)
            with self.assertRaisesRegex(RuntimeError, 'identity/hash'):
                runner.read_checkpoint(path, path.with_suffix('.json'), 'old', prior)
            prior.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'prior provenance'):
                runner.read_checkpoint(path, path.with_suffix('.json'), 'id', prior)

    def test_prior_sources_are_read_only_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'history'; path.write_bytes(b'original')
            frame = pd.DataFrame([{'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256_file(path)}])
            adopted.verify_prior_sources(frame)
            path.write_bytes(b'changed!')
            with self.assertRaisesRegex(RuntimeError, 'source changed'):
                adopted.verify_prior_sources(frame)
            self.assertEqual(path.read_bytes(), b'changed!')

    def test_production_is_offline_and_uses_isolated_adoption(self):
        source = (ROOT / 'src/100_generate_rapskartan_2025_map_product.py').read_text()
        for forbidden in ('query_scene_inventory', 'download_scene_archive', 'filter_scenes_to_fields'):
            self.assertNotIn(forbidden, source)
        self.assertIn('sys.addaudithook(offline_audit)', source)
        self.assertIn('2025_map_product_v3', source)
        self.assertIn('aggregate_adopted(', source)
        self.assertIn('replay_timeseries(', source)
        for name in ('RUN_RAPSKARTAN_2025_MAP_PRODUCT.bat', 'VERIFY_RAPSKARTAN_2025_MAP_PRODUCT.bat'):
            bat = (ROOT / name).read_text()
            self.assertNotIn('powershell', bat.lower())
            self.assertNotIn('AWS_ACCESS_KEY_ID', bat)

    def test_full_generator_gate_failure_partial_restart_and_provenance(self):
        from tests.test_rapskartan_map_product import prediction_row
        runner = load_script('100_generate_rapskartan_2025_map_product.py')
        day = '2025-05-20'
        predicted = pd.DataFrame([prediction_row('a', day, .95, True, municipality='1111'),
                                  prediction_row('b', day, .95, True, municipality='1112')])
        fields = predicted[['development_field_id', 'current_field_id', 'municipality_code', 'target_year', 'area_ha']].drop_duplicates().copy()
        fields['model_scope_status'] = 'MODEL_ELIGIBLE'; fields['geographic_fold'] = 0
        contract = copy.deepcopy(load_map_contract(ROOT))
        contract['geometry']['expected_eligible_fields'] = 2
        contract['frozen_feature_contract'] = {'temporal': {'cutoff_month_days': ['05-20']}}
        scenes = [{'item_id': 'scene', 'datetime': day+'T10:00:00Z', 'acquisition_date': day,
                   'cloud_cover': 0., 'assets': {'B02': {'bytes': 1}}}]
        receipt = json.loads((ROOT / adopted.ACCEPTANCE_REL).read_text())
        ts = pd.DataFrame({'development_field_id': fields.development_field_id, 'acquisition_date': day})
        snapshot = {'branch': runner.FEATURE_BRANCH, 'working_tree_clean': True, 'head_tree': 'tree', 'head': 'head'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            c, d, source, out, archive = [root / n for n in ('c', 'd', 'evidence', 'out', 'archive')]
            for folder in (c, d, source, out, archive): folder.mkdir()
            (c / 'model_artifacts_manifest.json').write_text('{}')
            (d / 'prediction_lock_manifest.json').write_text('{}')
            for name, frame in {'blind_field_selection.csv': fields, 'blind_prior_features.csv': fields,
                                'blind_predictions_locked.csv': predicted}.items(): save_table(d / name, frame)
            (source / 'diagnostic_manifest.json').write_text('{}')
            inventory = root / 'scene_inventory.json'; inventory.write_text(json.dumps({'items': scenes}))
            history = root / 'history'; history.write_bytes(b'original-history')
            args = Namespace(raw_root=root, stop_c_dir=c, stop_d_dir=d, accepted_parity_dir=source,
                             output_dir=out, scene_inventory=inventory, scene_archive=archive)
            def priors(local_fields, *_):
                return local_fields, pd.DataFrame([{'path': str(history), 'bytes': history.stat().st_size,
                    'sha256': sha256_file(history), 'history_year': 2024,
                    'municipality_code': local_fields.iloc[0].municipality_code}])
            def predictions(selection, *_): return predicted[predicted.development_field_id.isin(selection.development_field_id)].copy()
            with contextlib.ExitStack() as stack:
                for name, value in {'repository_snapshot': snapshot, 'verify_stop_c': None, 'verify_stop_d': None,
                    'load_map_contract': contract, 'runtime_contract': contract, 'runtime_versions': {'test': True},
                    'read_full_safe_2025_geometry': fields, 'select_parity_field_ids': fields.development_field_id.tolist(),
                    'validate_scenes': scenes, 'verify_evidence': (receipt, {}, {'artifacts': []}),
                    'verify_existing_archive': pd.DataFrame([{'bytes': 1}]), 'replay_timeseries': ts,
                    'build_blind_temporal_features': fields}.items():
                    stack.enter_context(patch.object(runner, name, return_value=value))
                stack.enter_context(patch.object(runner, 'make_predictions', side_effect=predictions))
                prior_call = stack.enter_context(patch.object(runner, 'build_blind_priors', side_effect=priors))
                aggregate = stack.enter_context(patch.object(runner, 'aggregate_adopted', return_value=ts))
                with patch.object(runner, 'compare_parity_predictions', return_value=(pd.DataFrame(), {'status': 'FAIL'})):
                    self.assertEqual(runner.generate(args, out), 1)
                    self.assertEqual(aggregate.call_count, 0)
                aggregate.side_effect = [ts, RuntimeError('simulated interruption')]
                self.assertEqual(runner.generate(args, out), 1)
                self.assertTrue((out / 'checkpoints/1111.parquet').is_file())
                self.assertTrue((out / 'source/prior_sources_1111.csv').is_file())
                aggregate.side_effect = None
                before = aggregate.call_count
                self.assertEqual(runner.generate(args, out), 0)
                self.assertEqual(aggregate.call_count - before, 1)
                self.assertTrue((out / 'full_map_manifest.json').is_file())
                self.assertEqual(len(pd.read_parquet(out / (day+'.parquet'))), 2)
                before = aggregate.call_count
                self.assertEqual(runner.generate(args, out), 0)
                self.assertEqual(aggregate.call_count, before)
                # A different runtime must not consume or overwrite finished products.
                product_hash = sha256_file(out / (day+'.parquet'))
                with patch.object(runner, 'runtime_versions', return_value={'changed': True}):
                    self.assertEqual(runner.generate(args, out), 1)
                self.assertEqual(sha256_file(out / (day+'.parquet')), product_hash)

    def test_verifier_packages_only_manifest_artifacts_and_logs(self):
        import zipfile
        verifier = load_script('101_verify_rapskartan_2025_map_product.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); out = root / 'out'; out.mkdir()
            (out / 'product.parquet').write_bytes(b'test-product')
            (out / 'checkpoints').mkdir(); (out / 'checkpoints/huge_scene.jp2').write_bytes(b'not-returned')
            write_json(out / 'full_map_manifest.json', {'artifacts': artifact_records(out, ['product.parquet'])})
            argv = ['verify', '--output-dir', str(out), '--stop-c-dir', str(root / 'c'), '--stop-d-dir', str(root / 'd')]
            with patch.object(sys, 'argv', argv), patch.object(sys, 'addaudithook'), patch.object(verifier, 'verify', return_value=0):
                self.assertEqual(verifier.main(), 0)
            packages = list(out.glob('rapskartan_full_map_*.zip')); self.assertEqual(len(packages), 1)
            with zipfile.ZipFile(packages[0]) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(set(z.namelist()), {'product.parquet', 'full_map_manifest.json', 'logs/stope_verify.log'})

    def test_independent_verifier_checks_parity_rows_not_only_pass_label(self):
        from tests.test_rapskartan_map_product import prediction_row
        from rapskartan_map_product_core import apply_product_memory_rule, compare_parity_predictions, sha256_lf_normalized_text
        verifier = load_script('101_verify_rapskartan_2025_map_product.py')
        days = ['2025-'+d for d in ('03-15', '03-31', '04-10', '04-20', '04-30', '05-10', '05-20', '05-31', '06-10')]
        predictions = pd.DataFrame([prediction_row(str(i), day, .95, True, municipality=str(1100+i)) for i in range(33) for day in days])
        contract = copy.deepcopy(load_map_contract(ROOT))
        contract['geometry'].update(expected_total_fields=33, expected_eligible_fields=33)
        product = apply_product_memory_rule(predictions, contract); product['model_scope_status'] = 'MODEL_ELIGIBLE'
        parity_rows, gate = compare_parity_predictions(predictions, predictions, contract)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); out = root / 'out'; c = root / 'c'; d = root / 'd'
            for folder in (out / 'qa', out / 'source/accepted_engine_evidence', root / 'config', root / 'analysis/rapskartan_v1', c, d):
                folder.mkdir(parents=True, exist_ok=True)
            (root / verifier.CONTRACT_REL).write_text('{}'); (root / verifier.ACCEPTED_STOPD_REL).write_text('{}')
            receipt = {'engine_profile': adopted.PROFILE, 'diagnostic_manifest_sha256': 'accepted', 'decisions': len(predictions)}
            write_json(root / adopted.ACCEPTANCE_REL, receipt); write_json(out / 'accepted_local_engine_v3.json', receipt)
            for name in ('run_context.json', 'source/scene_inventory.json', 'source/accepted_engine_evidence/diagnostic_manifest.json'):
                write_json(out / name, {})
            for day in days: product[product.cutoff_date.eq(day)].to_parquet(out / (day+'.parquet'), index=False)
            save_table(out / 'qa/local_engine_parity_rows.csv', parity_rows)
            write_json(out / 'qa/local_engine_parity.json', gate)
            save_table(d / 'blind_predictions_locked.csv', predictions)
            save_table(d / 'blind_field_selection.csv', predictions[['development_field_id']].drop_duplicates())
            save_table(out / 'source/scene_archive_inventory.csv', pd.DataFrame(columns=['path', 'bytes', 'stac_checksum']))
            history = root / 'history'; history.write_bytes(b'history')
            save_table(out / 'source/prior_source_inventory.csv', pd.DataFrame([{'path': str(history), 'bytes': 7, 'sha256': sha256_file(history)}]))
            write_json(out / 'qa/full_map_qa.json', {'status': 'PASS', 'ground_truth_present': False, 'scope': contract['scope'],
                'engine_profile': adopted.PROFILE, 'scene_order_policy': adopted.POLICY, 'offline_only': True,
                'accepted_diagnostic_manifest_sha256': 'accepted'})
            snapshot = {'branch': verifier.FEATURE_BRANCH, 'working_tree_clean': True, 'head': 'head', 'head_tree': 'tree'}
            def manifest():
                names = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name != 'full_map_manifest.json')
                write_json(out / 'full_map_manifest.json', {'status': 'PASS', 'repository_head': 'head', 'repository_tree': 'tree',
                    'contract_sha256': sha256_file(root / verifier.CONTRACT_REL),
                    'accepted_stopd_manifest_sha256': sha256_lf_normalized_text(root / verifier.ACCEPTED_STOPD_REL),
                    'artifacts': artifact_records(out, names)})
            manifest(); args = Namespace(stop_c_dir=c, stop_d_dir=d)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(verifier, 'ROOT', root))
                for name, value in {'repository_snapshot': snapshot, 'load_map_contract': contract, 'verify_stop_c': None,
                    'verify_stop_d': None, 'verify_evidence': None, 'verify_archive': None,
                    'select_parity_field_ids': sorted(predictions.development_field_id.unique())}.items():
                    stack.enter_context(patch.object(verifier, name, return_value=value))
                self.assertEqual(verifier.verify(args, out), 0)
                # Even with fresh artifact hashes and a claimed PASS summary, a changed decision fails.
                parity_rows.loc[0, 'predicted_at_frozen_p95_local'] = False
                save_table(out / 'qa/local_engine_parity_rows.csv', parity_rows); manifest()
                self.assertEqual(verifier.verify(args, out), 1)


if __name__ == '__main__': unittest.main()
