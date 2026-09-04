#!/usr/bin/env python3
"""Generate the full historical 2025 Rapskartan after the accepted blind gate."""
from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

from rapskartan_blind_prediction_core import (
    build_blind_priors, build_blind_temporal_features, frozen_runtime_contract,
    load_blind_contract, make_predictions, verify_stop_c,
)
from rapskartan_map_product_core import (
    ACCEPTED_STOPD_REL, CONTRACT_REL, FEATURE_BRANCH, add_outside_scope_rows,
    apply_product_memory_rule,
    compare_parity_predictions,
    full_model_selection, load_map_contract,
    read_full_safe_2025_geometry, select_parity_field_ids, sha256_bytes,
    sha256_file, sha256_lf_normalized_text, stable_json, verify_stop_d,
    write_product_manifest,
)
from rapskartan_s2_pilot_core import utc_now, write_dataframe, write_json
from rapskartan_v1_discovery_core import repository_snapshot
from rapskartan_adopted_engine import (
    ACCEPTANCE_REL, aggregate_adopted, copy_evidence, replay_timeseries, runtime_versions,
    verify_evidence, verify_existing_archive, verify_prior_sources,
)
from rapskartan_parity_diagnostic_core import Tee, ensure_separate_output, heartbeat, local_path, offline_audit, read_table, validate_scenes
from rapskartan_pixel_reference_core import run_lock
from rapskartan_scene_order_candidate import PROFILE, POLICY


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOP_C = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
DEFAULT_STOP_D = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD")
DEFAULT_OUT = ROOT / "data" / "derived" / "rapskartan_v1" / "2025_map_product_v3"
DEFAULT_INVENTORY = ROOT / "data/derived/rapskartan_v1/2025/source/scene_inventory.json"
DEFAULT_ARCHIVE = Path(r"C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\map_product_2025_scene_archive_v1")


def runtime_contract(stop_c: Path, map_contract: dict) -> dict:
    frozen = frozen_runtime_contract(stop_c, load_blind_contract(ROOT))
    combined = dict(map_contract)
    for key in ("model_version", "frozen_feature_contract_version", "frozen_model_contract_id", "frozen_feature_contract"):
        combined[key] = frozen[key]
    combined["selection"] = frozen["selection"]
    return combined


def atomic_parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)
    return sha256_file(path)


def checkpoint_id(snapshot: dict, contract: dict, scenes: list[dict], stop_c: Path) -> str:
    identity = {
        "repository_tree": snapshot["head_tree"],
        "contract_sha256": sha256_file(ROOT / CONTRACT_REL),
        "accepted_stopd_sha256": sha256_lf_normalized_text(ROOT / ACCEPTED_STOPD_REL),
        "model_manifest_sha256": sha256_file(stop_c / "model_artifacts_manifest.json"),
        "scenes": [(item["item_id"], item["datetime"]) for item in scenes],
        "product_rule": contract["product_rule"],
        "engine_profile": PROFILE, "scene_order_policy": POLICY,
        "engine_acceptance_sha256": sha256_lf_normalized_text(ROOT / ACCEPTANCE_REL),
        "runtime": runtime_versions(),
        "scene_metadata_sha256": sha256_bytes(stable_json(scenes).encode()),
    }
    return sha256_bytes(stable_json(identity).encode("utf-8"))


def read_checkpoint(path: Path, sidecar: Path, expected_id: str, prior_path: Path | None = None) -> pd.DataFrame | None:
    if not sidecar.is_file():
        return None
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if not path.is_file() or metadata.get("checkpoint_id") != expected_id or metadata.get("sha256") != sha256_file(path):
        raise RuntimeError(f"Municipality checkpoint identity/hash mismatch: {path}")
    if prior_path is not None and (not prior_path.is_file() or metadata.get('prior_sources_sha256') != sha256_file(prior_path)):
        raise RuntimeError('Municipality checkpoint prior provenance mismatch')
    frame = pd.read_parquet(path)
    if len(frame) != int(metadata["rows"]):
        raise RuntimeError('Municipality checkpoint row count mismatch')
    return frame


def write_checkpoint(path: Path, frame: pd.DataFrame, expected_id: str, prior_path: Path | None = None) -> None:
    digest = atomic_parquet(path, frame)
    write_json(path.with_suffix(".json"), {
        "schema_version": "rapskartan-2025-municipality-checkpoint-v1",
        "checkpoint_id": expected_id, "rows": len(frame),
        "fields": int(frame["field_id"].nunique()), "sha256": digest,
        'prior_sources_sha256': sha256_file(prior_path) if prior_path is not None else None,
    })


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--stop-c-dir", type=Path, default=DEFAULT_STOP_C)
    parser.add_argument("--stop-d-dir", type=Path, default=DEFAULT_STOP_D)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--scene-archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--scene-inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--accepted-parity-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sys.addaudithook(offline_audit)
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, local_path(value))
    if args.accepted_parity_dir is None:
        candidates = sorted((ROOT / 'data/derived/rapskartan_v1/2025_candidate_parity_v3').glob('run_*/diagnostic_manifest.json'))
        if len(candidates) != 1:
            raise RuntimeError('Expected one accepted V3 run; specify --accepted-parity-dir')
        args.accepted_parity_dir = local_path(candidates[0].parent)
    out = args.output_dir
    ensure_separate_output(out, [args.stop_c_dir, args.stop_d_dir, args.scene_archive,
                                args.accepted_parity_dir, args.scene_inventory.parent.parent])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'logs').mkdir(exist_ok=True)
    if shutil.disk_usage(out).free < 20 * 2**30:
        raise RuntimeError('Full map requires 20 GiB free output headroom; no downloads are planned')
    with run_lock(out), (out / 'logs/map_product.log').open('a', encoding='utf-8') as handle:
        with contextlib.redirect_stdout(Tee(sys.stdout, handle)), contextlib.redirect_stderr(Tee(sys.stderr, handle)):
            return generate(args, out)


def generate(args, out) -> int:
    started = time.monotonic()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "source", "qa", "checkpoints"):
        (out / name).mkdir(parents=True, exist_ok=True)
    try:
        print("[MAP] Verifying clean repository, frozen pre-blind model and accepted STOPPUNKT D...", flush=True)
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError(f"Map product requires clean branch {FEATURE_BRANCH}")
        stop_c = args.stop_c_dir.resolve()
        stop_d = args.stop_d_dir.resolve()
        map_contract = load_map_contract(ROOT)
        verify_stop_c(ROOT, stop_c)
        verify_stop_d(ROOT, stop_d, map_contract)
        contract = runtime_contract(stop_c, map_contract)

        print("[MAP] Reading identity/municipality/geometry only for all 2025 fields...", flush=True)
        geometry_path = args.raw_root.resolve() / map_contract["geometry"]["relative_path"]
        fields = read_full_safe_2025_geometry(geometry_path, map_contract)
        eligible = fields[fields["model_scope_status"] == "MODEL_ELIGIBLE"].copy()
        expected_eligible = int(map_contract["geometry"]["expected_eligible_fields"])
        if len(eligible) != expected_eligible:
            raise RuntimeError(f"Eligible field count {len(eligible)}, expected {expected_eligible}")
        selection = full_model_selection(fields)

        print("[MAP] Loading frozen scene inventory OFFLINE; no catalog or download requests...", flush=True)
        scene_document = json.loads(args.scene_inventory.read_text(encoding='utf-8'))
        scenes = validate_scenes(scene_document, map_contract)
        archive_bytes = sum(int(asset["bytes"]) for scene in scenes for asset in scene["assets"].values())
        blind_selection = pd.read_csv(stop_d / "blind_field_selection.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        blind_prior = pd.read_csv(stop_d / "blind_prior_features.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        locked = pd.read_csv(stop_d / "blind_predictions_locked.csv", dtype={"development_field_id": str, "current_field_id": str, "municipality_code": str})
        parity_ids = select_parity_field_ids(blind_selection, locked, map_contract)
        parity_fields = eligible[eligible["development_field_id"].isin(parity_ids)].copy()
        parity_selection = blind_selection[blind_selection["development_field_id"].isin(parity_ids)].copy()
        parity_prior = blind_prior[blind_prior["development_field_id"].isin(parity_ids)].copy()
        parity_locked = locked[locked["development_field_id"].isin(parity_ids)].copy()
        if len(parity_fields) != len(parity_ids):
            raise RuntimeError("Parity field identities do not resolve in frozen 2025 geometry")
        print('[MAP] Verifying accepted V3 evidence, identical pixel/order code and runtime...', flush=True)
        with heartbeat('accepted engine verification'):
            receipt, evidence_inputs, evidence_manifest = verify_evidence(
                args.accepted_parity_dir, ROOT, stop_c, stop_d, args.scene_inventory, parity_ids)
        run_id = checkpoint_id(snapshot, contract, scenes, stop_c)
        context_path = out / 'run_context.json'
        context = {'checkpoint_id': run_id, 'engine_profile': PROFILE, 'scene_order_policy': POLICY,
                   'accepted_diagnostic_manifest_sha256': receipt['diagnostic_manifest_sha256']}
        if context_path.exists() and json.loads(context_path.read_text(encoding='utf-8')) != context:
            raise RuntimeError('Full map output belongs to another engine/runtime/input identity; use a new output directory')
        write_json(context_path, context)
        shutil.copyfile(ROOT / CONTRACT_REL, out / 'map_product_contract.json')
        write_dataframe(out / 'qa/field_scope_inventory.csv', fields.groupby(['municipality_code', 'model_scope_status']).size().rename('fields').reset_index())
        shutil.copyfile(ROOT / ACCEPTANCE_REL, out / 'accepted_local_engine_v3.json')
        shutil.copyfile(args.scene_inventory, out / 'source/scene_inventory.json')
        copy_evidence(args.accepted_parity_dir, out / 'source/accepted_engine_evidence', evidence_manifest)
        print(f'[MAP] Hash-verifying {len(scenes)} existing scenes; {archive_bytes / 2**30:.2f} GiB. No downloads.', flush=True)
        archive_inventory = verify_existing_archive(scenes, args.scene_archive)
        write_dataframe(out / 'source/scene_archive_inventory.csv', archive_inventory)
        print('[MAP] Replaying verified V3 parity checkpoints through unchanged frozen models...', flush=True)
        with heartbeat('accepted parity checkpoint replay'):
            parity_ts = replay_timeseries(args.accepted_parity_dir, evidence_inputs)
        parity_temporal = build_blind_temporal_features(parity_ts, parity_selection, contract)
        parity_predictions = make_predictions(parity_selection, parity_prior, parity_temporal, stop_c, contract)
        parity_rows, parity_summary = compare_parity_predictions(parity_predictions, parity_locked, map_contract)
        write_dataframe(out / "qa" / "local_engine_parity_rows.csv", parity_rows)
        write_json(out / "qa" / "local_engine_parity.json", parity_summary)
        if parity_summary["status"] != "PASS":
            raise RuntimeError(f"LOCAL_ENGINE_PARITY_GATE: {parity_summary}")

        products = []
        source_rows = []
        codes = sorted(eligible["municipality_code"].astype(str).unique())
        print(f"[MAP] Generating frozen full-Skåne product in {len(codes)} restartable municipality shards...", flush=True)
        for number, code in enumerate(codes, start=1):
            checkpoint = out / "checkpoints" / f"{code}.parquet"
            prior_path = out / 'source' / f'prior_sources_{code}.csv'
            frame = read_checkpoint(checkpoint, checkpoint.with_suffix(".json"), run_id, prior_path)
            if frame is None:
                local_fields = eligible[eligible["municipality_code"].astype(str) == code].copy()
                local_selection = selection[selection["municipality_code"].astype(str) == code].copy()
                prior, sources = build_blind_priors(local_fields, args.raw_root.resolve(), contract)
                timeseries = aggregate_adopted(local_fields, scenes, args.scene_archive, contract,
                    out / 'checkpoints/dates' / code, run_id, progress_prefix=f'MAP-{code}', empty_template=parity_ts.iloc[:0])
                temporal = build_blind_temporal_features(timeseries, local_selection, contract)
                predictions = make_predictions(local_selection, prior, temporal, stop_c, contract)
                frame = apply_product_memory_rule(predictions, contract)
                # Persist provenance before the municipality checkpoint becomes reusable.
                write_dataframe(prior_path, sources)
                write_checkpoint(checkpoint, frame, run_id, prior_path)
                mode = "computed"
            else:
                mode = "checkpoint"
                if not prior_path.is_file():
                    raise RuntimeError(f'Municipality prior provenance missing: {code}')
                sources = read_table(prior_path)
                with heartbeat(f'{code} prior source verification'):
                    verify_prior_sources(sources)
            source_rows.extend(sources.to_dict('records'))
            products.append(frame)
            print(f"[MAP] municipalities {number}/{len(codes)} · {code} · {mode} · {frame['field_id'].nunique():,} eligible fields", flush=True)
        eligible_product = pd.concat(products, ignore_index=True)
        product = add_outside_scope_rows(eligible_product, fields, contract)
        expected_rows = len(fields) * len(contract["frozen_feature_contract"]["temporal"]["cutoff_month_days"])
        if len(product) != expected_rows or product.groupby(["field_id", "cutoff_date"]).size().ne(1).any():
            raise RuntimeError(f"Full map row/identity coverage is incomplete: {len(product)}/{expected_rows}")

        product_relatives = []
        for cutoff, frame in product.groupby("cutoff_date", sort=True):
            relative = f"{cutoff}.parquet"
            atomic_parquet(out / relative, frame.sort_values(["municipality_code", "field_id"], kind="mergesort").reset_index(drop=True))
            product_relatives.append(relative)
        status = product.groupby(["cutoff_date", "confidence_status", "model_scope_status"]).size().rename("fields").reset_index()
        municipality = product.groupby(["cutoff_date", "municipality_code"])["field_id"].nunique().rename("fields").reset_index()
        write_dataframe(out / "qa" / "status_distribution.csv", status)
        write_dataframe(out / "qa" / "municipality_coverage.csv", municipality)
        prior_inventory_path = out / "source" / "prior_source_inventory.csv"
        if source_rows:
            write_dataframe(prior_inventory_path, pd.DataFrame(source_rows).drop_duplicates("path").sort_values(["history_year", "municipality_code"]))
        elif not prior_inventory_path.is_file():
            raise RuntimeError("Prior source inventory is unavailable on a checkpoint-only rerun")

        qa = {
            "schema_version": "rapskartan-2025-full-map-qa-v1", "status": "PASS",
            "population_fields": len(fields), "model_eligible_fields": len(eligible),
            "outside_model_scope_fields": len(fields) - len(eligible), "cutoffs": len(product_relatives),
            "product_rows": len(product), "municipalities": int(product["municipality_code"].nunique()),
            "high_confidence_fields_final": int(product[product["cutoff_date"] == product["cutoff_date"].max()]["remembered_high_confidence"].sum()),
            "scene_items": len(scenes), "scene_assets": len(archive_inventory), "scene_archive_bytes": int(archive_inventory["bytes"].sum()),
            "parity": parity_summary, "ground_truth_columns": [], "ground_truth_present": False,
            "blind_benchmark_changed": False, "model_retuned": False, "threshold_retuned": False,
            "scope": map_contract["scope"], "elapsed_seconds": round(time.monotonic() - started, 3),
            "engine_profile": PROFILE, "scene_order_policy": POLICY,
            "accepted_diagnostic_manifest_sha256": receipt['diagnostic_manifest_sha256'],
            "offline_only": True,
        }
        write_json(out / "qa" / "full_map_qa.json", qa)
        relatives = [
            "map_product_contract.json", "source/scene_inventory.json", "source/scene_archive_inventory.csv",
            "source/prior_source_inventory.csv", "qa/field_scope_inventory.csv",
            "qa/local_engine_parity_rows.csv", "qa/local_engine_parity.json",
            "qa/status_distribution.csv", "qa/municipality_coverage.csv", "qa/full_map_qa.json",
            *product_relatives,
            'accepted_local_engine_v3.json', 'run_context.json',
            *[f'source/prior_sources_{code}.csv' for code in codes],
            *[f'source/accepted_engine_evidence/{r["path"]}' for r in evidence_manifest['artifacts']],
            'source/accepted_engine_evidence/diagnostic_manifest.json',
        ]
        counts = {key: qa[key] for key in (
            "population_fields", "model_eligible_fields", "outside_model_scope_fields", "cutoffs",
            "product_rows", "municipalities", "high_confidence_fields_final", "scene_items", "scene_assets",
            "scene_archive_bytes",
        )}
        write_product_manifest(
            out, relatives, repository_head=snapshot["head"], repository_tree=snapshot["head_tree"],
            contract_sha256=sha256_file(ROOT / CONTRACT_REL),
            accepted_stopd_sha256=sha256_lf_normalized_text(ROOT / ACCEPTED_STOPD_REL), counts=counts,
        )
        end_snapshot = repository_snapshot(ROOT)
        if end_snapshot['head'] != snapshot['head'] or not end_snapshot['working_tree_clean']:
            raise RuntimeError('Repository changed during full map generation')
        print("=" * 88)
        print("RAPSKARTAN SKANE V1 FULL HISTORICAL 2025 MAP PRODUCT: PASS")
        print("=" * 88)
        print(f"Fields: {len(fields):,} total · {len(eligible):,} modeled · {len(fields)-len(eligible):,} explicit outside scope")
        print(f"Cutoffs: {len(product_relatives)} · rows: {len(product):,} · municipalities: 33")
        print(f"Local-engine parity: PASS · P95 decision agreement {parity_summary['decision_agreement']:.3f}")
        print(f"Scene archive: {len(scenes)} scenes · {archive_inventory['bytes'].sum()/2**30:.2f} GiB")
        print("Ground truth in product: NO")
        print("Web/Sentinel-1/deployment/tag/merge: NO")
        print("Run the independent STOPPUNKT E verifier next.")
        return 0
    except Exception as exc:
        traceback.print_exc()
        (out / "logs" / "map_product_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"RAPSKARTAN FULL MAP PRODUCT: FAIL OR BLOCKED — {exc}")
        print("No web, Sentinel-1, deployment, tag or merge ran.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
