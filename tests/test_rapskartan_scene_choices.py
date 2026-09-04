from __future__ import annotations
import copy,hashlib,importlib.util,json,sys,tempfile,unittest,zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import rapskartan_scene_choice_core as core
from rapskartan_parity_diagnostic_core import save_table
from rapskartan_s2_pilot_core import artifact_records
from tests.test_rapskartan_pixel_cases import fixture
spec=importlib.util.spec_from_file_location('scene_choices_runner',ROOT/'src/105_compare_rapskartan_scene_choices.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class SceneChoiceTests(unittest.TestCase):
    def test_field_selection_is_bounded_deterministic_and_not_error_ranked(self):
        fields=pd.DataFrame({'development_field_id':[f'f{i:02}' for i in range(30)]})
        errors=pd.DataFrame({'development_field_id':fields.development_field_id[:6]})
        a=core.select_fields(fields,errors);b=core.select_fields(fields.sample(frac=1,random_state=4),errors)
        pd.testing.assert_frame_equal(a,b);self.assertEqual(len(a),12)
        self.assertEqual(sum(a.diagnostic_group=='existing_decision_mismatch'),6)
        with self.assertRaisesRegex(RuntimeError,'one to six'):core.select_fields(fields,fields[:7])

    def test_two_date_scene_budget_and_metadata_only_order_hypotheses(self):
        scenes=[]
        for day in core.DATES:
            scenes.extend([{'item_id':day+'_B','datetime':day+'T10:15:00Z','acquisition_date':day,'cloud_cover':.007034},
                           {'item_id':day+'_A','datetime':day+'T10:27:00Z','acquisition_date':day,'cloud_cover':.007326}])
        original=copy.deepcopy(scenes);result=core.ordering_hypotheses(core.bounded_scenes(scenes))
        first=result[result['rank']==1]
        self.assertTrue(first[first.hypothesis=='original_full_precision'].item_id.str.endswith('_B').all())
        self.assertTrue(first[first.hypothesis=='truncated_cloud_then_newest'].item_id.str.endswith('_A').all())
        self.assertTrue(result.cloud_truncated_2dp.eq(0).all())
        self.assertFalse(result.applied_to_engine.any());self.assertEqual(scenes,original)
        with self.assertRaisesRegex(RuntimeError,'sixteen'):core.bounded_scenes(scenes*5)
        with self.assertRaisesRegex(RuntimeError,'scope'):core.bounded_scenes(scenes[:2])

    def test_attribution_requires_all_statistics_and_counts_not_just_low_error(self):
        scene={'item_id':'test','acquisition_date':core.DATES[0],'cloud_cover':0}
        fields=pd.DataFrame({'development_field_id':['f']})
        row={'development_field_id':'f','acquisition_date':core.DATES[0],'valid_pixels':10,'data_quality_status':'VALID',**dict.fromkeys(core.METRICS,.2)}
        reference=pd.DataFrame([row]);frame=reference.copy()
        a=core.compare_scene(frame,reference,fields,scene);self.assertTrue(a.complete_single_scene_match.iloc[0])
        frame.loc[0,core.METRICS[0]]=np.nan
        a=core.compare_scene(frame,reference,fields,scene);self.assertFalse(a.complete_single_scene_match.iloc[0])
        self.assertTrue(pd.isna(core.summarize_matches(a).lowest_error_scene.iloc[0]))
        frame=reference.copy();frame.loc[0,'valid_pixels']=9
        self.assertFalse(core.compare_scene(frame,reference,fields,scene).complete_single_scene_match.iloc[0])
        a=core.compare_scene(frame.iloc[:0],reference,fields,scene)
        self.assertFalse(a.observation_present.iloc[0]);self.assertEqual(a.finite_pairs.iloc[0],0)

    def test_real_raster_scene_replay_and_nonoverlapping_scene(self):
        from shapely.affinity import translate
        with tempfile.TemporaryDirectory() as temp:
            archive=Path(temp);contract,fields,scenes=fixture(archive)
            empty=pd.DataFrame(columns=core.KEYS+core.METRICS)
            first=core.process_scene(fields,scenes[0],archive,contract,empty)
            self.assertEqual(len(first),1)
            other=fields.copy();other.geometry=other.geometry.map(lambda g:translate(g,1000000,1000000))
            self.assertTrue(core.process_scene(other,scenes[0],archive,contract,empty).empty)

    def test_source_manifest_rejects_modified_input_and_changed_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);source=base/'source';source.mkdir();root=base/'repo';(root/'src').mkdir(parents=True)
            names=['diagnostic_summary.json','diagnostic_inputs.json','selected_fields.csv','decision_mismatches.csv','local_timeseries.csv','reference_timeseries.csv']
            for name in names:(source/name).write_text('{}')
            (source/'diagnostic_summary.json').write_text(json.dumps({'repository_head':'a'*40,'engine_profile':'reference_pixels_v2'}))
            (source/'diagnostic_inputs.json').write_text(json.dumps({'engine_profile':'reference_pixels_v2'}))
            for name in ('rapskartan_local_candidate.py','rapskartan_map_product_core.py'):(root/'src'/name).write_bytes(b'code\r\n')
            manifest={'status':'DIAGNOSTICS_COMPLETE','artifacts':artifact_records(source,names)}
            (source/'diagnostic_manifest.json').write_text(json.dumps(manifest))
            with patch.object(core.subprocess,'run',return_value=Namespace(stdout=b'code\n')):
                core.verify_source(source,root)
                (root/'src/rapskartan_local_candidate.py').write_text('different')
                with self.assertRaisesRegex(RuntimeError,'code changed'):core.verify_source(source,root)
            (source/'selected_fields.csv').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'artifact mismatch'):core.verify_source(source,root)

    def test_complete_real_raster_run_reuses_scene_checkpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);archive=base/'archive';archive.mkdir()
            contract,fields,scenes=fixture(archive)
            for day,scene in zip(core.DATES,scenes):scene.update(acquisition_date=day,datetime=day+'T10:00:00Z')
            source=base/'candidate';source.mkdir();stop=base/'stop_d';stop.mkdir();product=base/'product';(product/'source').mkdir(parents=True);output=base/'output';output.mkdir()
            selection=pd.DataFrame(fields.drop(columns='geometry'));save_table(source/'selected_fields.csv',selection)
            save_table(source/'decision_mismatches.csv',selection[['development_field_id']])
            geometry=fields.to_crs(3006)
            save_table(stop/'blind_selection_geometry_wkb.csv',pd.DataFrame({'development_field_id':fields.development_field_id,'geometry_wkb_hex':[g.wkb_hex for g in geometry.geometry]}))
            (stop/'prediction_lock_manifest.json').write_text('{}');(source/'diagnostic_manifest.json').write_text('{}')
            (product/'source/scene_inventory.json').write_text(json.dumps({'items':scenes}))
            original={str(p):core.sha256_file(p) for p in archive.rglob('*.jp2')}
            empty=pd.DataFrame(columns=core.KEYS+core.METRICS)
            frames=[core.process_scene(fields,s,archive,contract,empty) for s in scenes]
            for name in ['local_timeseries.csv','reference_timeseries.csv']:save_table(source/name,pd.concat(frames))
            inputs={'scene_inventory_sha256':core.sha256_file(product/'source/scene_inventory.json'),'prediction_lock_sha256':core.sha256_file(stop/'prediction_lock_manifest.json')}
            args=Namespace(diagnostic_dir=source,stop_d_dir=stop,product_dir=product,scene_archive=archive)
            snapshot={'branch':runner.BRANCH,'working_tree_clean':True,'head':'test','head_tree':'test-tree'}
            with patch.object(runner,'repository_snapshot',return_value=snapshot),patch.object(runner,'verify_source',return_value=inputs),patch.object(runner,'verify_stop_d'),patch.object(runner,'load_map_contract',return_value=contract),patch.object(runner,'validate_scenes',return_value=scenes),patch.object(runner,'process_scene',wraps=core.process_scene) as process:
                out=runner.run(args,output);again=runner.run(args,output)
                self.assertEqual(out,again);self.assertEqual(process.call_count,2)
            summary=json.loads((out/'scene_choice_summary.json').read_text())
            self.assertEqual(summary['status'],'SCENE_COMPARISON_COMPLETE');self.assertFalse(summary['production_order_changed'])
            self.assertTrue(pd.read_csv(out/'scene_progress.csv')['mode'].eq('checkpoint').all())
            self.assertEqual(original,{str(p):core.sha256_file(p) for p in archive.rglob('*.jp2')})

    def test_main_packages_reports_not_images_or_checkpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);output=base/'output';argv=['scene','--output-dir',str(output)]
            for name in ['diagnostic-dir','stop-d-dir','product-dir','scene-archive']:argv += ['--'+name,str(base/name)]
            def fake_run(args,folder):
                out=folder/'run_test';(out/'checkpoints').mkdir(parents=True);(out/'checkpoints/scene.parquet').write_text('not packaged')
                (out/'scene_choice_summary.json').write_text('{"status":"SCENE_COMPARISON_COMPLETE"}');return out
            with patch.object(sys,'argv',argv),patch.object(sys,'addaudithook'),patch.object(runner,'run',side_effect=fake_run):self.assertEqual(runner.main(),0)
            package=next(output.glob('*.zip'))
            with zipfile.ZipFile(package) as z:
                self.assertIsNone(z.testzip());self.assertFalse(any('checkpoints' in n for n in z.namelist()))
                for item in json.loads(z.read('scene_choice_manifest.json'))['artifacts']:self.assertEqual(hashlib.sha256(z.read(item['path'])).hexdigest(),item['sha256'])


if __name__=='__main__':unittest.main()
