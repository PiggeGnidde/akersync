#!/usr/bin/env python3
"""Independent verifier for the full historical 2025 Rapskartan product."""
from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from rapskartan_blind_prediction_core import sha256_file, verify_stop_c
from rapskartan_map_product_core import (
    ACCEPTED_STOPD_REL, CONTRACT_REL, FEATURE_BRANCH, FORBIDDEN_PRODUCT_COLUMNS,
    _multihash_digest, load_map_contract, sha256_lf_normalized_text, verify_stop_d,
)
from rapskartan_v1_discovery_core import repository_snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOP_C = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC")
DEFAULT_STOP_D = Path(r"C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD")
DEFAULT_OUT = ROOT / "data" / "derived" / "rapskartan_v1" / "2025"


def verify_artifacts(root: Path, manifest: dict) -> None:
    for record in manifest.get("artifacts", []):
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Map manifest artifact mismatch: {record['path']}")


def verify_archive(inventory: pd.DataFrame) -> None:
    required = {"path", "bytes", "stac_checksum"}
    if required - set(inventory.columns) or inventory.empty:
        raise RuntimeError("Scene archive inventory is invalid")
    for number, row in enumerate(inventory.itertuples(index=False), start=1):
        path = Path(str(row.path))
        if not path.is_file() or path.stat().st_size != int(row.bytes):
            raise RuntimeError(f"Scene archive asset size mismatch: {path}")
        if not _multihash_digest(path, None if pd.isna(row.stac_checksum) else str(row.stac_checksum)):
            raise RuntimeError(f"Scene archive asset checksum mismatch: {path}")
        if number % 250 == 0 or number == len(inventory):
            print(f"[VERIFY] scene assets {number}/{len(inventory)} hash verified", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stop-c-dir", type=Path, default=DEFAULT_STOP_C)
    parser.add_argument("--stop-d-dir", type=Path, default=DEFAULT_STOP_D)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    try:
        snapshot = repository_snapshot(ROOT)
        if snapshot["branch"] != FEATURE_BRANCH or not snapshot["working_tree_clean"]:
            raise RuntimeError(f"Verifier requires clean branch {FEATURE_BRANCH}")
        contract = load_map_contract(ROOT)
        verify_stop_c(ROOT, args.stop_c_dir.resolve())
        verify_stop_d(ROOT, args.stop_d_dir.resolve(), contract)
        manifest_path = out / "full_map_manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("Full map manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "PASS":
            raise RuntimeError("Full map manifest is not PASS")
        if manifest.get("repository_head") != snapshot["head"] or manifest.get("repository_tree") != snapshot["head_tree"]:
            raise RuntimeError("Full map repository snapshot differs")
        if manifest.get("contract_sha256") != sha256_file(ROOT / CONTRACT_REL):
            raise RuntimeError("Full map contract hash differs")
        if manifest.get("accepted_stopd_manifest_sha256") != sha256_lf_normalized_text(ROOT / ACCEPTED_STOPD_REL):
            raise RuntimeError("Full map accepted STOPPUNKT D hash differs")
        verify_artifacts(out, manifest)

        parity = json.loads((out / "qa" / "local_engine_parity.json").read_text(encoding="utf-8"))
        gate = contract["parity_gate"]
        if (
            parity.get("status") != "PASS"
            or float(parity["decision_agreement"]) < float(gate["required_frozen_p95_decision_agreement"])
            or float(parity["data_quality_agreement"]) < float(gate["minimum_data_quality_agreement"])
            or float(parity["median_absolute_probability_delta"]) > float(gate["maximum_median_absolute_probability_delta"])
            or float(parity["p95_absolute_probability_delta"]) > float(gate["maximum_p95_absolute_probability_delta"])
        ):
            raise RuntimeError("Local scene engine parity gate is not PASS")

        cutoffs = [f"2025-{value}" for value in (
            "03-15", "03-31", "04-10", "04-20", "04-30", "05-10", "05-20", "05-31", "06-10",
        )]
        frames = []
        expected_fields = int(contract["geometry"]["expected_total_fields"])
        for cutoff in cutoffs:
            path = out / f"{cutoff}.parquet"
            frame = pd.read_parquet(path)
            if len(frame) != expected_fields or frame["field_id"].astype(str).nunique() != expected_fields:
                raise RuntimeError(f"{cutoff}: field coverage differs from full 2025 population")
            if set(frame["cutoff_date"].astype(str)) != {cutoff}:
                raise RuntimeError(f"{cutoff}: cutoff column mismatch")
            if FORBIDDEN_PRODUCT_COLUMNS & set(frame.columns):
                raise RuntimeError(f"{cutoff}: ground-truth/crop columns are present")
            if frame["ground_truth_present"].astype(bool).any():
                raise RuntimeError(f"{cutoff}: ground-truth marker is true")
            frames.append(frame)
        product = pd.concat(frames, ignore_index=True).sort_values(["field_id", "cutoff_date"], kind="mergesort").reset_index(drop=True)
        if product.groupby(["field_id", "cutoff_date"]).size().ne(1).any():
            raise RuntimeError("Product field/cutoff keys are not unique")
        if product["municipality_code"].astype(str).nunique() != 33:
            raise RuntimeError("Product does not cover all 33 municipalities")
        eligible = product["model_scope_status"] == "MODEL_ELIGIBLE"
        outside = product["model_scope_status"] == "OUTSIDE_AREA_SCOPE"
        expected_eligible = int(contract["geometry"]["expected_eligible_fields"])
        if product.loc[eligible, "field_id"].nunique() != expected_eligible:
            raise RuntimeError("Model-eligible field count differs")
        if product.loc[outside, "field_id"].nunique() != expected_fields - expected_eligible:
            raise RuntimeError("Outside-scope field count differs")
        if product.loc[outside, "p_raps"].notna().any() or not product.loc[outside, "confidence_status"].eq("NO_DATA").all():
            raise RuntimeError("Outside-scope fields silently received probabilities/status")
        finite = eligible & product["p_raps"].notna()
        expected_current = finite & product["p_raps"].ge(product["frozen_p95_threshold"])
        if not product["current_high_confidence"].astype(bool).equals(expected_current):
            raise RuntimeError("Current high-confidence decisions differ from frozen P95")
        expected_memory = product.groupby("field_id", sort=False)["current_high_confidence"].cummax().astype(bool)
        if not product["remembered_high_confidence"].astype(bool).equals(expected_memory):
            raise RuntimeError("Post-blind product memory is not monotonic/exact")
        expected_status = np.select(
            [expected_memory, ~finite, product["p_raps"].ge(0.5)],
            ["HIGH_CONFIDENCE", "NO_DATA", "POSSIBLE"], default="LOW",
        )
        if not product["confidence_status"].astype(str).equals(pd.Series(expected_status, index=product.index)):
            raise RuntimeError("Product confidence statuses do not follow the frozen product rule")

        archive = pd.read_csv(out / "source" / "scene_archive_inventory.csv", dtype={"stac_checksum": str})
        verify_archive(archive)
        qa = json.loads((out / "qa" / "full_map_qa.json").read_text(encoding="utf-8"))
        scope = qa.get("scope", {})
        if qa.get("status") != "PASS" or qa.get("ground_truth_present") is not False:
            raise RuntimeError("Full map QA is not PASS/label-free")
        for key in ("post_blind_model_retuning", "threshold_retuning", "sentinel1", "web", "deployment", "tag", "merge"):
            if scope.get(key) is not False:
                raise RuntimeError(f"Full map QA crossed forbidden scope: {key}")

        final = product[product["cutoff_date"] == max(cutoffs)]
        print("=" * 88)
        print("RAPSKARTAN SKANE V1 STOPPUNKT E MAP PRODUCT VERIFIER: PASS")
        print("=" * 88)
        print(f"Fields: {expected_fields:,} · modeled {expected_eligible:,} · explicit outside scope {expected_fields-expected_eligible:,}")
        print(f"Cutoffs: 9 · field/cutoff rows: {len(product):,} · municipalities: 33")
        print(f"Remembered high-confidence fields at 10 June: {int(final['remembered_high_confidence'].sum()):,}")
        print(f"Local-engine parity decisions: {float(parity['decision_agreement']):.3f} · archive assets: {len(archive):,} all hash verified")
        print("Ground truth in product: NO")
        print("Model/threshold retuning, web, Sentinel-1, deployment, tag, merge: NO")
        print("STOPPUNKT E")
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(f"RAPSKARTAN STOPPUNKT E MAP VERIFIER: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
