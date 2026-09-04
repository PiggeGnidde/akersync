"""Bounded offline source attribution; no production ordering changes."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from rapskartan_model_core import SPECTRAL_NAMES
from rapskartan_map_product_core import aggregate_local_scene_timeseries, local_asset_path, sha256_file
from rapskartan_parity_diagnostic_core import local_path, read_table

DATES = ('2025-03-21','2025-05-20')
MAX_FIELDS = 12
MAX_SCENES = 16
METRICS = [f'{b}_p{p}' for b in SPECTRAL_NAMES for p in (10,50,90)]
KEYS = ['development_field_id','acquisition_date']


def verify_source(folder: Path, root: Path):
    manifest=json.loads((folder/'diagnostic_manifest.json').read_text(encoding='utf-8'))
    records=manifest.get('artifacts',[])
    names=[r['path'] for r in records]
    required={'diagnostic_summary.json','diagnostic_inputs.json','selected_fields.csv',
              'decision_mismatches.csv','local_timeseries.csv','reference_timeseries.csv'}
    if manifest.get('status')!='DIAGNOSTICS_COMPLETE' or len(names)!=len(set(names)) or not required<=set(names):
        raise RuntimeError('Incomplete candidate diagnostic manifest')
    for record in records:
        path=local_path(folder/record['path'])
        if path.parent!=folder or not path.is_file() or path.stat().st_size!=int(record['bytes']) or sha256_file(path)!=record['sha256']:
            raise RuntimeError('Candidate diagnostic artifact mismatch')
    summary=json.loads((folder/'diagnostic_summary.json').read_text(encoding='utf-8'))
    inputs=json.loads((folder/'diagnostic_inputs.json').read_text(encoding='utf-8'))
    if summary.get('engine_profile')!='reference_pixels_v2' or inputs.get('engine_profile')!='reference_pixels_v2':
        raise RuntimeError('Scene comparison requires the completed v2 candidate diagnostic')
    head=summary.get('repository_head','')
    if not re.fullmatch('[0-9a-f]{40}',head):
        raise RuntimeError('Invalid candidate source commit')
    # Preserve the exact pixel processing being diagnosed, across LF/CRLF checkouts.
    for name in ('src/rapskartan_local_candidate.py','src/rapskartan_map_product_core.py'):
        result=subprocess.run(['git','show',f'{head}:{name}'],cwd=root,capture_output=True,check=True)
        normalize=lambda b:b.replace(b'\r\n',b'\n')
        if normalize((root/name).read_bytes())!=normalize(result.stdout):
            raise RuntimeError('Candidate pixel code changed since source diagnostic')
    return inputs


def select_fields(selection, mismatches):
    ids=sorted(set(mismatches.development_field_id))
    if not 1<=len(ids)<=6 or not set(ids)<=set(selection.development_field_id):
        raise RuntimeError('Expected one to six existing mismatch fields')
    if selection.development_field_id.duplicated().any():
        raise RuntimeError('Duplicate selected field identity')
    controls=[x for x in selection.development_field_id if x not in ids]
    controls=sorted(controls,key=lambda x:(hashlib.sha256(('scene-choice-controls-v1|'+x).encode()).hexdigest(),x))[:6]
    result=selection[selection.development_field_id.isin(ids+controls)].copy()
    result['diagnostic_group']=np.where(result.development_field_id.isin(ids),'existing_decision_mismatch','deterministic_control')
    if len(result)>MAX_FIELDS:raise RuntimeError('Field budget exceeded')
    return result.sort_values('development_field_id').reset_index(drop=True)


def bounded_scenes(scenes):
    chosen=[s for s in scenes if s['acquisition_date'] in DATES]
    if not chosen or len(chosen)>MAX_SCENES or {s['acquisition_date'] for s in chosen}!=set(DATES):
        raise RuntimeError('Two-date scene scope is missing or exceeds sixteen scenes')
    if len({s['item_id'] for s in chosen})!=len(chosen):
        raise RuntimeError('Duplicate scene identity')
    return sorted(chosen,key=lambda s:(s['acquisition_date'],s['item_id']))


def ordering_hypotheses(scenes):
    rows=[]
    for day in DATES:
        items=[s for s in scenes if s['acquisition_date']==day]
        def cloud(s):
            v=Decimal(str(s['cloud_cover']))
            if not v.is_finite() or not 0<=v<=100:raise RuntimeError('Invalid cloud percentage')
            return v.quantize(Decimal('.01'),rounding=ROUND_DOWN)
        newest={t:i for i,t in enumerate(sorted({s['datetime'] for s in items},reverse=True))}
        policies={
            'original_full_precision':lambda s:(float(s['cloud_cover']),s['item_id']),
            'truncated_cloud_then_id':lambda s:(cloud(s),s['item_id']),
            'truncated_cloud_then_newest':lambda s:(cloud(s),newest[s['datetime']],s['item_id']),
            'truncated_cloud_then_oldest':lambda s:(cloud(s),s['datetime'],s['item_id']),
        }
        for policy,key in policies.items():
            for rank,s in enumerate(sorted(items,key=key),1):
                rows.append({'acquisition_date':day,'hypothesis':policy,'rank':rank,'item_id':s['item_id'],
                             'datetime':s['datetime'],'cloud_full_precision':s['cloud_cover'],
                             'cloud_truncated_2dp':float(cloud(s)),'applied_to_engine':False})
    return pd.DataFrame(rows)


def process_scene(fields, scene, archive, contract, empty_template):
    import rasterio
    from rasterio.warp import transform_bounds
    from shapely.geometry import box
    with rasterio.open(local_asset_path(archive,scene,'SCL')) as source:
        bounds=transform_bounds(source.crs,fields.crs,*source.bounds,densify_pts=21)
    subset=fields[fields.geometry.intersects(box(*bounds))].copy()
    if subset.empty:return empty_template.copy()
    try:
        return aggregate_local_scene_timeseries(subset,[scene],archive,contract,
               engine_profile='reference_pixels_v2',progress_prefix='SCENE-CHOICE')
    except RuntimeError as exc:
        if str(exc)=='Local Sentinel-2 scene aggregation produced no field observations':
            return empty_template.copy()
        raise


def compare_scene(frame, reference, fields, scene):
    if frame.duplicated(KEYS).any() or reference.duplicated(KEYS).any():
        raise RuntimeError('Duplicate observation identity')
    local=frame.set_index(KEYS);ref=reference.set_index(KEYS);rows=[]
    for field in fields.development_field_id:
        key=(field,scene['acquisition_date'])
        if key not in ref.index:raise RuntimeError('Reference field/date is missing')
        r=ref.loc[key];a=local.loc[key] if key in local.index else None
        rv=r[METRICS].to_numpy(dtype=float)
        av=a[METRICS].to_numpy(dtype=float) if a is not None else np.full(len(METRICS),np.nan)
        both=np.isfinite(rv)&np.isfinite(av);delta=np.abs(av[both]-rv[both])
        complete=bool(both.all())
        counts=a is not None and int(a.valid_pixels)==int(r.valid_pixels)
        quality=a is not None and a.data_quality_status==r.data_quality_status
        rows.append({'development_field_id':field,'acquisition_date':key[1],'item_id':scene['item_id'],
                     'cloud_cover':scene['cloud_cover'],'observation_present':a is not None,
                     'valid_pixels_scene':int(a.valid_pixels) if a is not None else 0,'valid_pixels_reference':int(r.valid_pixels),
                     'quality_scene':a.data_quality_status if a is not None else 'NO_OBSERVATION',
                     'quality_reference':r.data_quality_status,'pixel_count_agrees':bool(counts),
                     'quality_agrees':bool(quality),'finite_pairs':int(both.sum()),'required_pairs':len(METRICS),
                     'matching_statistics_1e_7':int((delta<=1e-7).sum()),
                     'mean_abs_delta':float(delta.mean()) if delta.size else np.nan,
                     'max_abs_delta':float(delta.max()) if delta.size else np.nan,
                     'complete_single_scene_match':bool(complete and counts and quality and (delta<=1e-7).all())})
    return pd.DataFrame(rows)


def summarize_matches(comparison):
    rows=[]
    for (field,day),g in comparison.groupby(KEYS,sort=True):
        eligible=g[g.finite_pairs.eq(len(METRICS))].sort_values(['mean_abs_delta','max_abs_delta','item_id'])
        best=eligible.iloc[0] if not eligible.empty else None
        exact=g[g.complete_single_scene_match].item_id.tolist()
        rows.append({'development_field_id':field,'acquisition_date':day,
                     'complete_match_count':len(exact),'complete_matches_json':json.dumps(exact),
                     'lowest_error_scene':best.item_id if best is not None else None,
                     'lowest_mean_abs_delta':best.mean_abs_delta if best is not None else np.nan,
                     'interpretation':'single_scene_fingerprint_only_not_service_order_proof'})
    return pd.DataFrame(rows)
