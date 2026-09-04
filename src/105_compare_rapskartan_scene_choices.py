#!/usr/bin/env python3
"""Two dates, at most twelve fields and sixteen existing scenes; offline only."""
from __future__ import annotations

import argparse
import contextlib
import json
import platform
import shutil
import sys
import traceback
import zipfile
from datetime import datetime,timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from shapely import wkb

from rapskartan_map_product_core import load_map_contract,sha256_file,sha256_bytes,stable_json,verify_stop_d
from rapskartan_parity_diagnostic_core import (Tee,ensure_separate_output,heartbeat,local_path,offline_audit,
    read_table,save_table,read_day_checkpoint,save_day_checkpoint,validate_scenes,verify_day_assets)
from rapskartan_pixel_reference_core import run_lock
from rapskartan_scene_choice_core import (DATES,MAX_FIELDS,MAX_SCENES,verify_source,select_fields,
    bounded_scenes,ordering_hypotheses,process_scene,compare_scene,summarize_matches)
from rapskartan_s2_pilot_core import artifact_records,write_json
from rapskartan_v1_discovery_core import repository_snapshot

ROOT=Path(__file__).resolve().parents[1]
BRANCH='feature/rapskartan-skane-v1a'


def run(args,base):
    print('[SCENE-CHOICE] OFFLINE: two dates; no models, crop labels or production changes.',flush=True)
    snapshot=repository_snapshot(ROOT)
    if snapshot['branch']!=BRANCH or not snapshot['working_tree_clean']:
        raise RuntimeError(f'Scene comparison requires clean branch {BRANCH}')
    source=args.diagnostic_dir
    if source is None:
        matches=sorted((ROOT/'data/derived/rapskartan_v1/2025_candidate_parity_v2').glob('run_*/diagnostic_manifest.json'))
        if len(matches)!=1:raise RuntimeError('Expected one candidate diagnostic; specify --diagnostic-dir with its run folder')
        source=local_path(matches[0].parent)
    ensure_separate_output(base,[source,args.stop_d_dir,args.product_dir,args.scene_archive])
    with heartbeat('verifying source diagnostic and STOP D'):
        inputs=verify_source(source,ROOT)
        contract=load_map_contract(ROOT)
        verify_stop_d(ROOT,args.stop_d_dir,contract)
    inventory=args.product_dir/'source/scene_inventory.json'
    if sha256_file(inventory)!=inputs['scene_inventory_sha256'] or sha256_file(args.stop_d_dir/'prediction_lock_manifest.json')!=inputs['prediction_lock_sha256']:
        raise RuntimeError('Scene inventory or locked prediction source differs from candidate diagnostic')
    scenes=bounded_scenes(validate_scenes(json.loads(inventory.read_text(encoding='utf-8')),contract))
    selected=select_fields(read_table(source/'selected_fields.csv'),read_table(source/'decision_mismatches.csv'))
    geometry=read_table(args.stop_d_dir/'blind_selection_geometry_wkb.csv')
    selected_geometry=selected.merge(geometry[['development_field_id','geometry_wkb_hex']],on='development_field_id',validate='one_to_one')
    if len(selected_geometry)!=len(selected):raise RuntimeError('Missing locked field geometry')
    fields=gpd.GeoDataFrame(selected_geometry.drop(columns='geometry_wkb_hex'),
                           geometry=[wkb.loads(v,hex=True) for v in selected_geometry.geometry_wkb_hex],crs=3006).to_crs(32633)
    if fields.geometry.is_empty.any() or not fields.geometry.is_valid.all():raise RuntimeError('Invalid locked field geometry')
    identity_inputs={'schema_version':'offline-scene-choice-v1','repository_tree':snapshot['head_tree'],
        'diagnostic_manifest_sha256':sha256_file(source/'diagnostic_manifest.json'),
        'scene_inventory_sha256':sha256_file(inventory),'prediction_lock_sha256':inputs['prediction_lock_sha256'],
        'dates':list(DATES),'field_ids':selected.development_field_id.tolist(),'scene_ids':[s['item_id'] for s in scenes],
        'engine_profile':'reference_pixels_v2','python':platform.python_version(),'rasterio':rasterio.__version__,
        'gdal':rasterio.__gdal_version__,'proj':rasterio.__proj_version__}
    identity=sha256_bytes(stable_json(identity_inputs).encode())
    out=base/f'run_{identity[:16]}';out.mkdir(parents=True,exist_ok=True)
    write_json(out/'scene_choice_inputs.json',identity_inputs)
    save_table(out/'selected_fields.csv',selected)
    save_table(out/'scene_order_hypotheses.csv',ordering_hypotheses(scenes))
    write_json(out/'scene_inventory.json',{'items':scenes})
    reference=read_table(source/'reference_timeseries.csv')
    baseline=read_table(source/'local_timeseries.csv')
    subset=lambda f:f[f.development_field_id.isin(selected.development_field_id)&f.acquisition_date.isin(DATES)].copy()
    reference,baseline=subset(reference),subset(baseline)
    if len(reference)!=len(selected)*len(DATES):raise RuntimeError('Reference scope does not contain both dates for every field')
    save_table(out/'reference_timeseries.csv',reference);save_table(out/'baseline_timeseries.csv',baseline)
    print(f'[SCENE-CHOICE] {len(selected)}/{MAX_FIELDS} fields; {len(scenes)}/{MAX_SCENES} scenes; output {out}',flush=True)
    parts,comparisons,verified,progress=[],[],[],[]
    for i,scene in enumerate(scenes,1):
        day,item=scene['acquisition_date'],scene['item_id']
        print(f'[SCENE-CHOICE] {i}/{len(scenes)} {item}',flush=True)
        with heartbeat('checking eleven existing scene assets'):
            verified.extend(verify_day_assets([scene],args.scene_archive))
        checkpoint=out/'checkpoints'/item
        frame=read_day_checkpoint(checkpoint,day,identity)
        mode='checkpoint'
        if frame is None:
            with heartbeat('single-scene pixel processing'):
                frame=process_scene(fields,scene,args.scene_archive,contract,baseline.iloc[:0])
            save_day_checkpoint(checkpoint,day,identity,frame);mode='computed'
        comparisons.append(compare_scene(frame,reference,selected,scene))
        if not frame.empty:
            part=frame.copy();part['item_id']=item;parts.append(part)
        progress.append({'item_id':item,'mode':mode,'rows':len(frame)})
        print(f'[SCENE-CHOICE] {i}/{len(scenes)} complete; {len(frame)} field observations; {mode}',flush=True)
    comparison=pd.concat(comparisons,ignore_index=True)
    save_table(out/'scene_comparison.csv',comparison)
    save_table(out/'best_single_scene.csv',summarize_matches(comparison))
    all_rows=pd.concat(parts,ignore_index=True) if parts else baseline.iloc[:0].assign(item_id=pd.Series(dtype=str))
    save_table(out/'single_scene_timeseries.csv',all_rows)
    save_table(out/'verified_scene_assets.csv',pd.DataFrame(verified));save_table(out/'scene_progress.csv',pd.DataFrame(progress))
    write_json(out/'scene_choice_summary.json',{'status':'SCENE_COMPARISON_COMPLETE','dates':list(DATES),
        'fields':len(selected),'scenes':len(scenes),'single_scene_rows':len(all_rows),
        'field_dates_with_complete_single_scene_match':int(comparison.groupby(['development_field_id','acquisition_date']).complete_single_scene_match.any().sum()),
        'comparison_tolerance':1e-7,'offline_only':True,'new_requests':0,'models_loaded':False,
        'production_order_changed':False,'production_parity_approved':False,
        'interpretation':'Single-scene attribution diagnostic. Lowest error is not proof of service tie-breaking or an authorized production rule.'})
    end=repository_snapshot(ROOT)
    if end['head']!=snapshot['head'] or not end['working_tree_clean']:raise RuntimeError('Repository changed during comparison')
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic-dir',type=Path)
    parser.add_argument('--stop-d-dir',type=Path,default=Path(r'C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD'))
    parser.add_argument('--product-dir',type=Path,default=ROOT/'data/derived/rapskartan_v1/2025')
    parser.add_argument('--scene-archive',type=Path,default=Path(r'C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\map_product_2025_scene_archive_v1'))
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data/derived/rapskartan_v1/2025_scene_choice_v1')
    args=parser.parse_args();sys.addaudithook(offline_audit)
    for name,value in vars(args).items():
        if value is not None:setattr(args,name,local_path(value))
    base=args.output_dir
    ensure_separate_output(base,[args.stop_d_dir,args.product_dir,args.scene_archive,
        args.diagnostic_dir or ROOT/'data/derived/rapskartan_v1/2025_candidate_parity_v2'])
    base.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(base).free<2*2**30:raise RuntimeError('Scene comparison requires 2 GiB output headroom')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    log=base/f'scene_choice_console_{stamp}.log'
    with run_lock(base):
        with log.open('w',encoding='utf-8') as handle:
            with contextlib.redirect_stdout(Tee(sys.stdout,handle)),contextlib.redirect_stderr(Tee(sys.stderr,handle)):
                try:out=run(args,base)
                except Exception:
                    traceback.print_exc();print(f'SCENE COMPARISON BLOCKED. Keep checkpoints; return this log: {log}');return 1
        shutil.copyfile(log,out/'scene_choice_console.log')
        files=sorted(p.name for p in out.iterdir() if p.is_file() and p.name!='scene_choice_manifest.json')
        write_json(out/'scene_choice_manifest.json',{'status':'SCENE_COMPARISON_COMPLETE','artifacts':artifact_records(out,files)})
        package=base/f'rapskartan_scene_choices_{stamp}.zip'
        with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for name in [*files,'scene_choice_manifest.json']:archive.write(out/name,name)
        with zipfile.ZipFile(package) as archive:
            if archive.testzip() is not None:raise RuntimeError('Scene comparison ZIP is damaged')
        print(f'RETURN THIS ZIP: {package}',flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
