"""Opt-in metadata-order adapter; the v2 pixel engine is not modified."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
import json

import pandas as pd

from rapskartan_map_product_core import sha256_file
from rapskartan_parity_diagnostic_core import read_day_checkpoint, read_table
from rapskartan_scene_choice_core import DATES, verify_source

PROFILE = "reference_scene_order_v3"
POLICY = "cloud_percent_truncated_2dp_then_item_id"


def ordered_metadata(scenes):
    """Copy metadata, replacing only the engine's sorting key, never source files.

    The unchanged v2 engine reads cloud_cover only to sort scenes. Paths,
    acquisition times, asset values and pixel operations remain identical.
    """
    result = []
    for scene in scenes:
        cloud = Decimal(str(scene['cloud_cover']))
        if not cloud.is_finite() or not 0 <= cloud <= 100:
            raise RuntimeError('Invalid cloud percentage for candidate ordering')
        result.append({**scene, 'cloud_cover': float(cloud.quantize(Decimal('.01'), rounding=ROUND_DOWN))})
    return result


def order_report(scenes):
    records, changed = [], []
    for day in sorted({s['acquisition_date'] for s in scenes}):
        original = sorted([s for s in scenes if s['acquisition_date'] == day],
                          key=lambda s: (float(s['cloud_cover']), s['item_id']))
        candidate = sorted(ordered_metadata(original), key=lambda s: (s['cloud_cover'], s['item_id']))
        old_ids, new_ids = [s['item_id'] for s in original], [s['item_id'] for s in candidate]
        if old_ids != new_ids:
            changed.append(day)
        ranks = {item: i for i, item in enumerate(new_ids, 1)}
        for i, scene in enumerate(original, 1):
            records.append({'acquisition_date': day, 'item_id': scene['item_id'],
                            'cloud_full_precision': scene['cloud_cover'],
                            'cloud_sort_key_2dp': ordered_metadata([scene])[0]['cloud_cover'],
                            'rank_v2': i, 'rank_v3': ranks[scene['item_id']],
                            'date_order_changed': old_ids != new_ids})
    return pd.DataFrame(records), changed


def prepare_reuse(source, root, current_inputs, scenes):
    previous = verify_source(source, root)
    summary = json.loads((source / 'diagnostic_summary.json').read_text(encoding='utf-8'))
    for name in ('scene_inventory_sha256', 'prediction_lock_sha256', 'model_manifest_sha256',
                 'field_ids', 'runtime'):
        if previous.get(name) != current_inputs.get(name) or name not in previous:
            raise RuntimeError(f'V2 reuse identity mismatch: {name}')
    for name in ('reference_feature_replay_vs_locked', 'reference_timeseries_replay_vs_locked'):
        if summary.get(name, {}).get('status') != 'PASS':
            raise RuntimeError('V2 reference replay must have passed before reuse')
    from rapskartan_map_product_core import sha256_bytes, stable_json
    identity = sha256_bytes(stable_json(previous).encode('utf-8'))
    if identity != summary.get('diagnostic_id'):
        raise RuntimeError('V2 diagnostic identity is inconsistent')
    report, changed = order_report(scenes)
    # This experiment is explicitly bounded to the two diagnosed dates.
    if set(changed) - set(DATES):
        raise RuntimeError('Candidate ordering changes dates outside the approved two-date scope')
    baseline = read_table(source / 'local_timeseries.csv')
    keys = ['development_field_id', 'acquisition_date']
    dates = {s['acquisition_date'] for s in scenes}
    if (baseline.duplicated(keys).any() or set(baseline.acquisition_date) != dates
            or set(baseline.development_field_id) != set(current_inputs['field_ids'])
            or len(baseline) != summary.get('observations_local')
            or len(dates) != summary.get('acquisition_dates')):
        raise RuntimeError('V2 timeseries scope is inconsistent')
    return {'source': source, 'identity': identity, 'baseline': baseline,
            'changed_dates': changed, 'report': report,
            'provenance': {'source_manifest_sha256': sha256_file(source / 'diagnostic_manifest.json'),
                           'source_diagnostic_id': identity, 'scene_order_policy': POLICY,
                           'changed_dates': changed, 'unchanged_dates': sorted(dates - set(changed)),
                           'reuse_method': 'hash_verified_v2_parquet_checked_against_manifest_csv'}}


def reuse_day(reuse, day):
    if day in reuse['changed_dates']:
        raise RuntimeError('Cannot reuse a date whose scene ordering changed')
    frame = read_day_checkpoint(reuse['source'] / 'checkpoints', day, reuse['identity'])
    if frame is None:
        raise RuntimeError(f'Original V2 checkpoint missing for {day}; no automatic full replay')
    expected = reuse['baseline'][reuse['baseline'].acquisition_date.eq(day)]
    keys = ['development_field_id', 'acquisition_date']
    try:
        pd.testing.assert_frame_equal(
            frame.sort_values(keys).reset_index(drop=True),
            expected.sort_values(keys).reset_index(drop=True),
            check_dtype=False, check_exact=False, rtol=0, atol=1e-14)
    except AssertionError as exc:
        raise RuntimeError(f'V2 checkpoint disagrees with manifest timeseries for {day}') from exc
    return frame
