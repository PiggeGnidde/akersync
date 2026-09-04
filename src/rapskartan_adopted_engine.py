"""Hash-bound adoption of the reviewed V3 local engine; offline only."""
from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from rapskartan_map_product_core import aggregate_local_scene_timeseries, sha256_file, sha256_bytes, stable_json
from rapskartan_parity_diagnostic_core import (
    heartbeat, local_path, read_day_checkpoint, read_table, save_day_checkpoint, verify_day_assets,
)
from rapskartan_scene_order_candidate import PROFILE, POLICY, ordered_metadata

ACCEPTANCE_REL = 'analysis/rapskartan_v1/accepted_local_engine_v3.json'
PIXEL_CODE = ('src/rapskartan_map_product_core.py', 'src/rapskartan_local_candidate.py',
              'src/rapskartan_scene_order_candidate.py')


def runtime_versions():
    import rasterio
    return {'python': platform.python_version(), 'platform': platform.platform(),
            'packages': {name: importlib.metadata.version(name) for name in
                         ('numpy', 'pandas', 'scikit-learn', 'rasterio', 'shapely', 'pyproj', 'geopandas', 'joblib', 'pyarrow')},
            'gdal': rasterio.__gdal_version__, 'proj': rasterio.__proj_version__}


def verify_evidence(source, root, stop_c, stop_d, scene_file, field_ids):
    receipt = json.loads((root / ACCEPTANCE_REL).read_text(encoding='utf-8'))
    manifest_path = source / 'diagnostic_manifest.json'
    if sha256_file(manifest_path) != receipt['diagnostic_manifest_sha256']:
        raise RuntimeError('Accepted V3 diagnostic manifest differs')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'DIAGNOSTICS_COMPLETE':
        raise RuntimeError('Accepted V3 diagnostic is incomplete')
    for record in manifest['artifacts']:
        path = local_path(source / record['path'])
        if path.parent != source or not path.is_file() or path.stat().st_size != record['bytes'] or sha256_file(path) != record['sha256']:
            raise RuntimeError('Accepted V3 diagnostic artifact differs')
    summary = json.loads((source / 'diagnostic_summary.json').read_text(encoding='utf-8'))
    inputs = json.loads((source / 'diagnostic_inputs.json').read_text(encoding='utf-8'))
    if (summary.get('repository_head') != receipt['repository_head'] or summary.get('diagnostic_id') != receipt['diagnostic_id']
            or summary.get('engine_profile') != PROFILE or receipt['engine_profile'] != PROFILE
            or summary.get('scene_order_candidate', {}).get('scene_order_policy') != POLICY):
        raise RuntimeError('Accepted V3 engine identity differs')
    if sha256_bytes(stable_json(inputs).encode()) != receipt['diagnostic_id']:
        raise RuntimeError('Accepted V3 input identity differs')
    for gate in ('local_engine_vs_locked', 'reference_feature_replay_vs_locked', 'reference_timeseries_replay_vs_locked'):
        if summary.get(gate, {}).get('status') != 'PASS':
            raise RuntimeError('Accepted V3 parity/reference replay is not PASS')
    for name, value in {'fields': receipt['fields'], 'acquisition_dates': receipt['acquisition_dates'],
                        'observations_local': receipt['observations']}.items():
        if summary.get(name) != value:
            raise RuntimeError('Accepted V3 evidence scope differs')
    if summary['local_engine_vs_locked']['rows'] != receipt['decisions']:
        raise RuntimeError('Accepted V3 decision coverage differs')
    expected = {'scene_inventory_sha256': sha256_file(scene_file),
                'prediction_lock_sha256': sha256_file(stop_d / 'prediction_lock_manifest.json'),
                'model_manifest_sha256': sha256_file(stop_c / 'model_artifacts_manifest.json'),
                'field_ids': field_ids, 'runtime': runtime_versions()}
    for name, value in expected.items():
        if inputs.get(name) != value:
            raise RuntimeError(f'Accepted V3 runtime/input mismatch: {name}')
    for name in PIXEL_CODE:
        old = subprocess.run(['git', 'show', f"{receipt['repository_head']}:{name}"], cwd=root, check=True, capture_output=True).stdout
        if old.replace(b'\r\n', b'\n') != (root / name).read_bytes().replace(b'\r\n', b'\n'):
            raise RuntimeError(f'Accepted V3 pixel/order code changed: {name}')
    return receipt, inputs, manifest


def replay_timeseries(source, inputs):
    baseline = read_table(source / 'local_timeseries.csv')
    keys = ['development_field_id', 'acquisition_date']
    if baseline.duplicated(keys).any() or set(baseline.development_field_id) != set(inputs['field_ids']):
        raise RuntimeError('Accepted V3 timeseries identity is invalid')
    identity = sha256_bytes(stable_json(inputs).encode())
    parts = []
    for day in sorted(baseline.acquisition_date.unique()):
        frame = read_day_checkpoint(source / 'checkpoints', day, identity)
        if frame is None:
            raise RuntimeError(f'Accepted V3 checkpoint missing: {day}')
        expected = baseline[baseline.acquisition_date.eq(day)]
        def canonical(value):
            value = value.sort_values(keys).reset_index(drop=True)
            return value.astype(object).where(value.notna(), None)
        try:
            pd.testing.assert_frame_equal(canonical(frame), canonical(expected), check_dtype=False,
                                          check_exact=False, rtol=0, atol=1e-14)
        except AssertionError as exc:
            raise RuntimeError(f'Accepted V3 checkpoint does not match report: {day}') from exc
        parts.append(frame)
    return pd.concat(parts, ignore_index=True).sort_values(keys).reset_index(drop=True)


def copy_evidence(source, destination, manifest):
    destination.mkdir(parents=True, exist_ok=True)
    for name in [r['path'] for r in manifest['artifacts']] + ['diagnostic_manifest.json']:
        shutil.copyfile(source / name, destination / name)


def verify_existing_archive(scenes, archive):
    from rapskartan_map_product_core import local_asset_path
    records = []
    for number, scene in enumerate(scenes, 1):
        with heartbeat(f"archive {number}/{len(scenes)} checksums"):
            verify_day_assets([scene], archive)
        for band, asset in scene['assets'].items():
            records.append({'item_id': scene['item_id'], 'band': band, 'path': str(local_asset_path(archive, scene, band)),
                            'bytes': asset['bytes'], 'stac_checksum': asset['checksum']})
        if number % 10 == 0 or number == len(scenes):
            print(f'[MAP] archive scenes {number}/{len(scenes)} hash verified; no downloads', flush=True)
    return pd.DataFrame(records)


def aggregate_adopted(fields, scenes, archive, contract, checkpoint_dir, identity, *, progress_prefix, empty_template=None):
    parts = []
    dates = sorted({s['acquisition_date'] for s in scenes})
    # Binding field IDs also protects a municipality/date cache from another shard.
    identity = sha256_bytes(stable_json({'run': identity, 'engine': PROFILE,
        'fields': sorted(fields.development_field_id.astype(str))}).encode())
    for number, day in enumerate(dates, 1):
        frame = read_day_checkpoint(checkpoint_dir, day, identity)
        mode = 'checkpoint'
        if frame is None:
            with heartbeat(f'{progress_prefix} {day} pixels'):
                try:
                    frame = aggregate_local_scene_timeseries(fields,
                        ordered_metadata([s for s in scenes if s['acquisition_date'] == day]), archive, contract,
                        progress_prefix=progress_prefix, engine_profile='reference_pixels_v2')
                except RuntimeError as exc:
                    if str(exc) != 'Local Sentinel-2 scene aggregation produced no field observations':
                        raise
                    frame = (empty_template.copy() if empty_template is not None else
                             pd.DataFrame(columns=['development_field_id', 'acquisition_date']))
            save_day_checkpoint(checkpoint_dir, day, identity, frame)
            mode = 'computed'
        parts.append(frame)
        print(f'[{progress_prefix}] dates {number}/{len(dates)}; {day}; rows {len(frame)}; {mode}', flush=True)
    nonempty = [part for part in parts if not part.empty]
    if not nonempty:
        raise RuntimeError('Municipality has no field observations over the entire period')
    return pd.concat(nonempty, ignore_index=True).sort_values(['development_field_id', 'acquisition_date']).reset_index(drop=True)


def verify_prior_sources(frame):
    required = {'path', 'bytes', 'sha256'}
    if frame.empty or required - set(frame.columns):
        raise RuntimeError('Municipality prior provenance is missing')
    for row in frame.itertuples(index=False):
        path = local_path(Path(row.path))
        if not path.is_file() or path.stat().st_size != row.bytes or sha256_file(path) != row.sha256:
            raise RuntimeError('Municipality prior source changed')
