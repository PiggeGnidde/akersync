#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the formal ÅkerPuls Split Fusion QA v1 freeze. Zero PU."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"
C7C_SUMMARY = Path(r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation\c7c_summary.json")
C7D_SUMMARY = Path(r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7d_blind_fusion_qa\c7d_summary.json")
FUSION_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json")

EXPECTED_FUSION_SHA = "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316"
EXPECTED_BLIND_KEY_SHA = "d2553241211545cb8c0ffdb110e3f063680024af3b17eef818e6fb4cf9a14879"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def main() -> int:
    cfg = read_json(CFG)
    require(cfg["schema_version"] == "akerpuls-split-fusion-qa-v1", "Wrong freeze schema")
    require(cfg["status"] == "FROZEN_QA_RANKING_NOT_AUTOMATIC_GEOMETRY", "Wrong freeze status")
    require(cfg["fusion"]["development_n"] == 367, "Development n changed")
    require(cfg["fusion"]["signals"] == [
        "prototype_p_splitmerge_2026",
        "separation_ratio",
        "true_loo_min_child_dice",
    ], "Frozen signal list changed")
    require(abs(sum(cfg["fusion"]["weights"]) - 1.0) < 1e-12, "Fusion weights do not sum to one")
    require(all(abs(float(w) - 1.0 / 3.0) < 1e-12 for w in cfg["fusion"]["weights"]), "Fusion weights changed")
    require(abs(float(cfg["fusion"]["development_p90"]) - 0.781017) < 1e-12, "P90 changed")
    require(abs(float(cfg["fusion"]["development_p95"]) - 0.843688) < 1e-12, "P95 changed")
    require(cfg["fusion"]["source_freeze_sha256"] == EXPECTED_FUSION_SHA, "Fusion SHA in config changed")
    require(cfg["candidate_input"]["requires_old_locked_split_gate"] is False, "Old locked gate accidentally required")
    require(cfg["candidate_input"]["requires_rejected_sep_ge_4_gate"] is False, "Rejected sep>=4 gate accidentally required")

    policy = cfg["policy"]
    require(policy["automatic_split"] is False, "Automatic split must remain false")
    require(policy["automatic_merge"] is False, "Automatic merge must remain false")
    require(policy["automatic_geometry_replacement"] is False, "Automatic geometry replacement must remain false")
    require(policy["product_use"] == "QA_RANKING_AND_REVIEW_PRIORITY_ONLY", "Product use changed")
    require(not any(bool(v) for v in cfg["guards"].values()), "Freeze guards unexpectedly enable forbidden actions")

    for p in (FUSION_FREEZE, C7C_SUMMARY, C7D_SUMMARY):
        if not p.exists():
            raise FileNotFoundError(p)

    got_sha = sha256_file(FUSION_FREEZE)
    require(got_sha == EXPECTED_FUSION_SHA, f"Frozen fusion artifact changed: {got_sha}")

    c7c = read_json(C7C_SUMMARY)
    require(c7c.get("status") == "PASS", "C7C is not PASS")
    require(c7c.get("fields") == 1000, "C7 field count changed")
    require(c7c.get("baseline_split_candidates") == 131, "C7 baseline candidate count changed")
    require(c7c.get("fusion_ge_dev_p90") == 15, "C7 P90 census count changed")
    require(c7c.get("fusion_ge_dev_p95") == 9, "C7 P95 census count changed")
    require(c7c.get("fusion_freeze_sha256") == EXPECTED_FUSION_SHA, "C7C fusion SHA mismatch")
    require(c7c.get("fusion_refit") is False, "C7C fusion was refit")
    require(c7c.get("thresholds_tuned") is False, "C7C thresholds were tuned")

    c7d = read_json(C7D_SUMMARY)
    require(c7d.get("status") == "PASS", "C7D is not PASS")
    require(c7d.get("blind_images") == 20, "C7D blind image count changed")
    require(c7d.get("p90_census_images") == 15, "C7D P90 census count changed")
    require(c7d.get("p95_within_p90_census") == 9, "C7D P95 census count changed")
    require(c7d.get("near_p90_control_images") == 5, "C7D control count changed")
    require(c7d.get("blind_key_sha256") == EXPECTED_BLIND_KEY_SHA, "C7D blind-key SHA mismatch")
    require(c7d.get("fusion_freeze_sha256") == EXPECTED_FUSION_SHA, "C7D fusion SHA mismatch")
    require(c7d.get("fusion_refit") is False, "C7D fusion was refit")
    require(c7d.get("thresholds_tuned") is False, "C7D thresholds were tuned")

    val = cfg["independent_holdout_validation"]
    require(val["p95"]["liberal_ty_mty_or_m"] == "9/9", "Frozen P95 visual result changed")
    require(val["p95"]["f"] == "0/9", "Frozen P95 false count changed")
    require(val["p90"]["liberal_ty_mty_or_m"] == "13/15", "Frozen P90 visual result changed")
    require(val["p90"]["f"] == "0/15", "Frozen P90 false count changed")

    print("AKERPULS SPLIT FUSION QA V1 FREEZE VERIFICATION")
    print("SCHEMA=akerpuls-split-fusion-qa-v1")
    print(f"FUSION_FREEZE_SHA256={got_sha}")
    print("DEVELOPMENT_CANDIDATES=367")
    print("FUSION_DEV_P90=0.781017 FUSION_DEV_P95=0.843688")
    print("C7_FIELDS=1000 BASELINE_CANDIDATES=131 P90_CENSUS=15 P95_CENSUS=9")
    print("C7_P95_LIBERAL=9/9 C7_P95_FALSE=0/9")
    print("C7_P90_LIBERAL=13/15 C7_P90_FALSE=0/15")
    print("AUTOMATIC_SPLIT=FALSE")
    print("AUTOMATIC_MERGE=FALSE")
    print("AUTOMATIC_GEOMETRY_REPLACEMENT=FALSE")
    print("PRODUCT_USE=QA_RANKING_AND_REVIEW_PRIORITY_ONLY")
    print("SENTINEL_HUB_PU_USED=0")
    print("AKERPULS_SPLIT_FUSION_QA_V1_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
