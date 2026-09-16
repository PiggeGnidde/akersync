#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze ÅkerPuls preliminary 2026 split geometry v1.

This is a policy/product freeze, not a geometry-generation stage. It verifies the
already frozen P95 proposal package, the first blind no-line human audit, the
pre-reveal geometry-audit freeze and the revealed geometry-audit analysis. It
then writes a 618-field product-status index and an immutable v1 freeze contract.

V1 policy:
  * official 2025 geometry remains canonical;
  * frozen P95 + LINE_AVAILABLE => PRELIM_2026_SPLIT_PROPOSAL;
  * frozen P95 + NO_SHARED_INTERFACE => NO_GEOMETRY_PROPOSAL;
  * proposal geometry is the unchanged frozen primary 10 m K2 interface line;
  * no smoothing, gap filling, model/fusion/threshold retuning, merge or automatic
    official-geometry replacement is performed.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")

EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_FIRST_HUMAN_AUDIT_FREEZE_SHA256 = "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4"
EXPECTED_PROPOSAL_FREEZE_SHA256 = "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a"
EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256 = "089cd1d90daa9252e93ddbe4004c7afad5f0c00ec8d54293b43fc6915e4983f0"

EXPECTED_P95 = 618
EXPECTED_LINE_AVAILABLE = 613
EXPECTED_NO_INTERFACE = 5

# Clean first P95 audit: proposed line was NOT shown.
EXPECTED_FIRST_AUDIT_P95_N = 50
EXPECTED_FIRST_AUDIT_P95_STRICT = 19
EXPECTED_FIRST_AUDIT_P95_BROAD = 39

# Second audit: line was shown; geometry placement is the primary endpoint.
EXPECTED_GEOM_AUDIT_N = 100
EXPECTED_GEOM_SPLIT_POSITIVE = 80
EXPECTED_LINE_STRICT_ON_SPLIT = 73
EXPECTED_LINE_BROAD_ON_SPLIT = 78
EXPECTED_LINE_WRONG_ON_SPLIT = 2

STATUS = "FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1"
OUTPUT_DIRNAME = "akerpuls_preliminary_geometry_v1_freeze"
FREEZE_NAME = "AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json"
MANIFEST_NAME = "akerpuls_preliminary_geometry_v1_manifest.json"
INDEX_NAME = "akerpuls_preliminary_geometry_v1_index.csv"
REPORT_NAME = "AKERPULS_PRELIMINARY_GEOMETRY_V1_REPORT.md"

POLICY = {
    "canonical_geometry": "OFFICIAL_2025_GEOMETRY",
    "candidate_scope": "EXACT_FROZEN_D2C_P95_POPULATION",
    "line_available_status": "PRELIM_2026_SPLIT_PROPOSAL",
    "no_shared_interface_status": "NO_GEOMETRY_PROPOSAL",
    "proposal_geometry_artifact": "p95_primary_split_line_review.gpkg",
    "proposal_geometry_method": "LONGEST_CONTIGUOUS_RAW_10M_K2_INTERFACE",
    "proposal_is_review_only": True,
    "smoothing": False,
    "gap_filling": False,
    "automatic_geometry_replacement": False,
    "merge_automation": False,
    "human_audit_labels_used_as_per_field_product_gate": False,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def close(a: float, b: float, tol: float = 1e-12) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)


def verify_first_audit(d2c: Path) -> dict[str, Any]:
    p = d2c / "d2c_visual_audit_freeze_v1" / "D2C_HUMAN_AUDIT_FREEZE_V1.json"
    if not p.is_file():
        raise FileNotFoundError(p)
    if sha256_file(p) != EXPECTED_FIRST_HUMAN_AUDIT_FREEZE_SHA256:
        raise RuntimeError("First human-audit freeze SHA changed")
    x = read_json(p)
    if x.get("status") != "FROZEN_D2C_HUMAN_AUDIT_V1":
        raise RuntimeError("First human-audit freeze status changed")
    if x.get("parent_d2c_freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("First human-audit parent D2C binding changed")
    rows = {r["audit_group"]: r for r in x.get("stratum_metrics", [])}
    p95 = rows.get("P95_HIGH_PRIORITY")
    if not p95:
        raise RuntimeError("First audit is missing P95 stratum metrics")
    if int(p95.get("audit_n", -1)) != EXPECTED_FIRST_AUDIT_P95_N:
        raise RuntimeError("First P95 audit n changed")
    if int(p95.get("strict_positive_n", -1)) != EXPECTED_FIRST_AUDIT_P95_STRICT:
        raise RuntimeError("First P95 strict count changed")
    if int(p95.get("broad_positive_n", -1)) != EXPECTED_FIRST_AUDIT_P95_BROAD:
        raise RuntimeError("First P95 broad count changed")
    if not close(p95.get("strict_precision", -1), 0.38) or not close(p95.get("broad_precision", -1), 0.78):
        raise RuntimeError("First P95 audit precision changed")
    return x


def verify_proposal_freeze(d2c: Path) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    fp = d2c / "d2c_p95_split_line_freeze_v1" / "P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json"
    if not fp.is_file():
        raise FileNotFoundError(fp)
    if sha256_file(fp) != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("P95 proposal freeze SHA changed")
    x = read_json(fp)
    if x.get("status") != "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1":
        raise RuntimeError("P95 proposal freeze status changed")
    if x.get("parent_d2c_freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("P95 proposal parent D2C binding changed")
    if x.get("parent_human_audit_freeze_sha256") != EXPECTED_FIRST_HUMAN_AUDIT_FREEZE_SHA256:
        raise RuntimeError("P95 proposal first-audit binding changed")
    if int(x.get("p95_fields", -1)) != EXPECTED_P95:
        raise RuntimeError("P95 proposal population changed")
    if int(x.get("line_available_fields", -1)) != EXPECTED_LINE_AVAILABLE:
        raise RuntimeError("P95 line-available census changed")
    if int(x.get("no_shared_interface_fields", -1)) != EXPECTED_NO_INTERFACE:
        raise RuntimeError("P95 no-interface census changed")
    contract = x.get("geometry_contract", {})
    if contract.get("primary_line") != "LONGEST_CONTIGUOUS_PART_OF_RAW_INTERFACE":
        raise RuntimeError("P95 primary-line geometry method changed")
    if contract.get("smoothing") is not False or contract.get("gap_filling") is not False:
        raise RuntimeError("P95 proposal geometry contract is no longer raw/unsmoothed")

    hashes = x.get("source_output_hashes", {})
    required = {
        "p95_split_proposal_summary.csv",
        "p95_primary_split_line_review.gpkg",
        "p95_official_2025_parents_review.gpkg",
        "p95_raw_k2_interface_review.gpkg",
        "p95_b2_child_evidence_review.gpkg",
    }
    if set(hashes) != required:
        raise RuntimeError(f"Proposal source output set changed: {sorted(hashes)}")
    for name, rec in hashes.items():
        p = Path(rec["path"])
        if not p.is_file():
            raise FileNotFoundError(p)
        if sha256_file(p) != rec.get("sha256") or int(p.stat().st_size) != int(rec.get("bytes", -1)):
            raise RuntimeError(f"Frozen proposal artifact changed: {name}")

    srec = hashes["p95_split_proposal_summary.csv"]
    summary = pd.read_csv(Path(srec["path"]), encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    if len(summary) != EXPECTED_P95 or summary.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Proposal summary is not 618 unique P95 fields")
    counts = summary.proposal_status.astype(str).value_counts().to_dict()
    if counts != {"LINE_AVAILABLE": EXPECTED_LINE_AVAILABLE, "NO_SHARED_INTERFACE": EXPECTED_NO_INTERFACE}:
        raise RuntimeError(f"Proposal summary status census changed: {counts}")
    if not bool(summary.reconstructed_d2a_exact.astype(bool).all()):
        raise RuntimeError("Not all P95 proposal rows are exact D2A reconstructions")
    return x, summary, hashes


def verify_geometry_audit_freeze(d2c: Path) -> dict[str, Any]:
    p = d2c / "d2c_p95_geometry_audit_freeze_v1" / "P95_GEOMETRY_AUDIT_FREEZE_V1.json"
    if not p.is_file():
        raise FileNotFoundError(p)
    if sha256_file(p) != EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Pre-reveal geometry-audit freeze SHA changed")
    x = read_json(p)
    if x.get("status") != "FROZEN_P95_GEOMETRY_AUDIT_V1":
        raise RuntimeError("Pre-reveal geometry-audit freeze status changed")
    if x.get("parent_proposal_freeze_sha256") != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("Pre-reveal geometry-audit proposal binding changed")
    if x.get("blind_key_opened_by_this_stage") is not False or x.get("reveal_executed") is not False:
        raise RuntimeError("Pre-reveal geometry audit no longer certifies blind state")
    return x


def verify_reveal(d2c: Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
    d = d2c / "d2c_p95_geometry_audit_reveal_v1"
    mp = d / "p95_geometry_audit_reveal_manifest.json"
    sp = d / "P95_GEOMETRY_AUDIT_REVEAL_SUMMARY_V1.json"
    if not mp.is_file() or not sp.is_file():
        raise FileNotFoundError(f"Missing reveal manifest/summary under {d}")
    m = read_json(mp)
    if m.get("status") != "REVEALED_P95_GEOMETRY_AUDIT_V1":
        raise RuntimeError("Reveal status changed")
    if m.get("parent_geometry_audit_freeze_sha256") != EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Reveal pre-reveal-freeze binding changed")
    if m.get("parent_proposal_freeze_sha256") != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("Reveal proposal-freeze binding changed")
    guards = {
        "reveal": m.get("reveal_executed") is True,
        "blind_opened": m.get("blind_key_opened") is True,
        "model": m.get("model_executed") is False,
        "thresholds": m.get("thresholds_tuned") is False,
        "fusion": m.get("fusion_refit") is False,
        "smoothing": m.get("smoothing") is False,
        "gap": m.get("gap_filling") is False,
        "merge": m.get("merge_executed") is False,
        "official": m.get("official_2025_geometry_replaced") is False,
        "mutation": m.get("automatic_geometry_mutation") is False,
    }
    if not all(guards.values()):
        raise RuntimeError(f"Reveal guards changed: {guards}")
    for name, rec in m.get("output_hashes", {}).items():
        p = Path(rec["path"])
        if not p.is_file() or sha256_file(p) != rec.get("sha256"):
            raise RuntimeError(f"Reveal output changed: {name}")

    s = read_json(sp)
    if s.get("status") != "REVEALED_P95_GEOMETRY_AUDIT_V1":
        raise RuntimeError("Reveal summary status changed")
    if int(s.get("sample_n", -1)) != EXPECTED_GEOM_AUDIT_N:
        raise RuntimeError("Geometry audit sample n changed")
    if int(s.get("line_population_n", -1)) != EXPECTED_LINE_AVAILABLE or int(s.get("p95_population_n", -1)) != EXPECTED_P95:
        raise RuntimeError("Geometry audit population census changed")
    if int(s.get("no_interface_n", -1)) != EXPECTED_NO_INTERFACE:
        raise RuntimeError("Geometry audit no-interface census changed")
    met = s.get("metrics", {})
    if int(met["split_broad"]["k"]) != EXPECTED_GEOM_SPLIT_POSITIVE or int(met["split_broad"]["n"]) != EXPECTED_GEOM_AUDIT_N:
        raise RuntimeError("Geometry-audit split-positive result changed")
    if int(met["conditional_on_split_positive_line_strict"]["k"]) != EXPECTED_LINE_STRICT_ON_SPLIT:
        raise RuntimeError("Conditional strict line result changed")
    if int(met["conditional_on_split_positive_line_broad"]["k"]) != EXPECTED_LINE_BROAD_ON_SPLIT:
        raise RuntimeError("Conditional broad line result changed")
    if int(met["conditional_on_split_positive_line_wrong"]["k"]) != EXPECTED_LINE_WRONG_ON_SPLIT:
        raise RuntimeError("Conditional wrong-line result changed")
    for key in (
        "conditional_on_split_positive_line_strict",
        "conditional_on_split_positive_line_broad",
        "conditional_on_split_positive_line_wrong",
    ):
        if int(met[key]["n"]) != EXPECTED_GEOM_SPLIT_POSITIVE:
            raise RuntimeError(f"Conditional denominator changed for {key}")
    return s, sha256_file(mp), m


def build_index(summary: pd.DataFrame) -> pd.DataFrame:
    x = summary[["parent_field_id_2025", "analysis_cell_id", "fusion_score", "proposal_status"]].copy()
    x["preliminary_geometry_v1_status"] = x.proposal_status.astype(str).map({
        "LINE_AVAILABLE": "PRELIM_2026_SPLIT_PROPOSAL",
        "NO_SHARED_INTERFACE": "NO_GEOMETRY_PROPOSAL",
    })
    if x.preliminary_geometry_v1_status.isna().any():
        raise RuntimeError("Unexpected proposal status while building v1 product index")
    x["canonical_geometry"] = "OFFICIAL_2025_GEOMETRY"
    x["proposal_geometry_artifact"] = x.proposal_status.astype(str).map({
        "LINE_AVAILABLE": POLICY["proposal_geometry_artifact"],
        "NO_SHARED_INTERFACE": "",
    })
    x["proposal_geometry_method"] = x.proposal_status.astype(str).map({
        "LINE_AVAILABLE": POLICY["proposal_geometry_method"],
        "NO_SHARED_INTERFACE": "",
    })
    x["adoption_state"] = "REVIEW_ONLY_NOT_CANONICAL"
    x = x.sort_values("parent_field_id_2025").reset_index(drop=True)
    return x


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    args = ap.parse_args()

    head = git_guard()
    d2c = Path(args.d2c_dir)
    out = d2c / OUTPUT_DIRNAME

    print("AKERPULS_PRELIM_GEOM_V1_PROGRESS=VERIFY_FROZEN_LINEAGE_AND_POLICY_INPUTS", flush=True)
    first = verify_first_audit(d2c)
    proposal, summary, proposal_hashes = verify_proposal_freeze(d2c)
    pre_reveal = verify_geometry_audit_freeze(d2c)
    reveal, reveal_manifest_sha, reveal_manifest = verify_reveal(d2c)

    if out.exists():
        mp = out / MANIFEST_NAME
        fp = out / FREEZE_NAME
        if not mp.is_file() or not fp.is_file():
            raise RuntimeError(f"Existing v1 freeze directory incomplete: {out}")
        old = read_json(mp)
        if old.get("status") != STATUS:
            raise RuntimeError("Existing v1 freeze status changed")
        if sha256_file(fp) != old.get("preliminary_geometry_v1_freeze_sha256"):
            raise RuntimeError("Existing v1 freeze SHA changed")
        for rec in old.get("output_hashes", {}).values():
            p = Path(rec["path"])
            if not p.is_file() or sha256_file(p) != rec.get("sha256"):
                raise RuntimeError(f"Existing v1 freeze output changed: {p}")
        print("AKERPULS PRELIMINARY GEOMETRY V1 FREEZE")
        print("STATUS=FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1_CACHED")
        print(f"PRELIMINARY_GEOMETRY_V1_FREEZE_SHA256={old['preliminary_geometry_v1_freeze_sha256']}")
        print(f"OUTPUT={out}")
        return 0

    index = build_index(summary)
    counts = index.preliminary_geometry_v1_status.value_counts().to_dict()
    if counts != {
        "PRELIM_2026_SPLIT_PROPOSAL": EXPECTED_LINE_AVAILABLE,
        "NO_GEOMETRY_PROPOSAL": EXPECTED_NO_INTERFACE,
    }:
        raise RuntimeError(f"V1 product index census changed: {counts}")

    out.mkdir(parents=True, exist_ok=False)
    index_path = out / INDEX_NAME
    index.to_csv(index_path, index=False, encoding="utf-8-sig")

    first_p95_strict = EXPECTED_FIRST_AUDIT_P95_STRICT / EXPECTED_FIRST_AUDIT_P95_N
    first_p95_broad = EXPECTED_FIRST_AUDIT_P95_BROAD / EXPECTED_FIRST_AUDIT_P95_N
    line_strict = EXPECTED_LINE_STRICT_ON_SPLIT / EXPECTED_GEOM_SPLIT_POSITIVE
    line_broad = EXPECTED_LINE_BROAD_ON_SPLIT / EXPECTED_GEOM_SPLIT_POSITIVE
    line_wrong = EXPECTED_LINE_WRONG_ON_SPLIT / EXPECTED_GEOM_SPLIT_POSITIVE

    freeze = {
        "schema_version": "akerpuls-preliminary-geometry-v1-freeze",
        "status": STATUS,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "decision": "SUFFICIENTLY_GOOD_FOR_PRELIMINARY_2026_GEOMETRY_V1",
        "lineage": {
            "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
            "first_human_audit_freeze_sha256": EXPECTED_FIRST_HUMAN_AUDIT_FREEZE_SHA256,
            "p95_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
            "pre_reveal_geometry_audit_freeze_sha256": EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256,
            "reveal_manifest_sha256": reveal_manifest_sha,
        },
        "population": {
            "p95_fields": EXPECTED_P95,
            "prelim_2026_split_proposal": EXPECTED_LINE_AVAILABLE,
            "no_geometry_proposal": EXPECTED_NO_INTERFACE,
        },
        "product_policy": POLICY,
        "validation_evidence": {
            "first_blind_p95_audit_line_hidden": {
                "n": EXPECTED_FIRST_AUDIT_P95_N,
                "strict_split_n": EXPECTED_FIRST_AUDIT_P95_STRICT,
                "strict_split_rate": first_p95_strict,
                "broad_split_n": EXPECTED_FIRST_AUDIT_P95_BROAD,
                "broad_split_rate": first_p95_broad,
                "role": "PRIMARY_SPLIT_EXISTENCE_VALIDATION",
            },
            "second_blind_geometry_audit_line_visible": {
                "n": EXPECTED_GEOM_AUDIT_N,
                "split_positive_n": EXPECTED_GEOM_SPLIT_POSITIVE,
                "conditional_line_strict_n": EXPECTED_LINE_STRICT_ON_SPLIT,
                "conditional_line_strict_rate": line_strict,
                "conditional_line_broad_n": EXPECTED_LINE_BROAD_ON_SPLIT,
                "conditional_line_broad_rate": line_broad,
                "conditional_line_wrong_n": EXPECTED_LINE_WRONG_ON_SPLIT,
                "conditional_line_wrong_rate": line_wrong,
                "role": "PRIMARY_LINE_PLACEMENT_VALIDATION",
                "cueing_caveat": "The cyan proposal line was visible; second-audit split rate is corroborative rather than independent split ground truth.",
            },
            "reveal_descriptive_full_p95_joint_strict": reveal["descriptive_extrapolation"]["joint_strict_rate_if_5_no_interface_count_as_failures_in_full_618_p95"],
            "reveal_descriptive_full_p95_joint_broad": reveal["descriptive_extrapolation"]["joint_broad_rate_if_5_no_interface_count_as_failures_in_full_618_p95"],
            "evidence_scope": "Visual Sentinel-2 audit, not farmer/official 2026 ground truth. Descriptive validation only.",
        },
        "source_artifacts": {
            "proposal_output_hashes": proposal_hashes,
            "reveal_output_hashes": reveal_manifest.get("output_hashes", {}),
            "product_index": INDEX_NAME,
        },
        "guards": {
            "model_executed": False,
            "thresholds_tuned": False,
            "fusion_refit": False,
            "smoothing": False,
            "gap_filling": False,
            "merge_executed": False,
            "official_2025_geometry_replaced": False,
            "automatic_geometry_mutation": False,
            "human_labels_used_as_per_field_gate": False,
        },
        "versioning": {
            "v1_is_frozen": True,
            "future_smoothing_or_confidence_filter_requires_new_version": True,
            "future_automatic_geometry_adoption_requires_new_policy_and_validation": True,
        },
        "next_step": "Downstream ÅkerPuls modules may consume PRELIM_2026_SPLIT_PROPOSAL as a review-only overlay while official 2025 geometry remains canonical.",
    }
    freeze_path = out / FREEZE_NAME
    write_json(freeze_path, freeze)
    freeze_sha = sha256_file(freeze_path)

    report = f"""# ÅkerPuls preliminary geometry v1 — formal freeze

Status: `{STATUS}`

## Product decision
ÅkerPuls preliminary geometry v1 is accepted as **sufficiently good for a preliminary 2026 split-proposal product**.
It is not an automatic replacement for official 2025 field geometry.

## Frozen product policy
- P95 population: {EXPECTED_P95} fields.
- `PRELIM_2026_SPLIT_PROPOSAL`: {EXPECTED_LINE_AVAILABLE} fields with a frozen primary line.
- `NO_GEOMETRY_PROPOSAL`: {EXPECTED_NO_INTERFACE} fields without a shared K2 interface.
- Official 2025 geometry remains canonical.
- Proposal line = longest contiguous part of the raw 10 m K2 interface.
- No smoothing or gap filling.
- No per-field human-audit gate is applied to the 613 proposals.
- No automatic merge or geometry replacement.

## Validation basis
First blind P95 audit, with no proposal line shown (cleaner split-existence endpoint):
- strict `TYDLIG_SPLIT`: {EXPECTED_FIRST_AUDIT_P95_STRICT}/{EXPECTED_FIRST_AUDIT_P95_N} = {100*first_p95_strict:.1f}%
- broad `TYDLIG+MÖJLIG`: {EXPECTED_FIRST_AUDIT_P95_BROAD}/{EXPECTED_FIRST_AUDIT_P95_N} = {100*first_p95_broad:.1f}%

Second blind line-geometry audit, conditional on a human-visible split:
- strict `RATT_GRANS`: {EXPECTED_LINE_STRICT_ON_SPLIT}/{EXPECTED_GEOM_SPLIT_POSITIVE} = {100*line_strict:.2f}%
- broad `RATT+NARA`: {EXPECTED_LINE_BROAD_ON_SPLIT}/{EXPECTED_GEOM_SPLIT_POSITIVE} = {100*line_broad:.2f}%
- wrong line: {EXPECTED_LINE_WRONG_ON_SPLIT}/{EXPECTED_GEOM_SPLIT_POSITIVE} = {100*line_wrong:.2f}%

The cyan line was visible in the second audit, so its split-rate is corroborative rather than independent split ground truth. The primary endpoint there is line placement.

Reveal-stage descriptive full-P95 joint rates (the five no-interface fields counted as failures):
- strict: {100*float(reveal['descriptive_extrapolation']['joint_strict_rate_if_5_no_interface_count_as_failures_in_full_618_p95']):.2f}%
- broad: {100*float(reveal['descriptive_extrapolation']['joint_broad_rate_if_5_no_interface_count_as_failures_in_full_618_p95']):.2f}%

These are visual Sentinel-2 audit results, not independent farmer records or official 2026 geometry ground truth.

## Lineage
- D2C freeze: `{EXPECTED_D2C_FREEZE_SHA256}`
- first human-audit freeze: `{EXPECTED_FIRST_HUMAN_AUDIT_FREEZE_SHA256}`
- P95 proposal freeze: `{EXPECTED_PROPOSAL_FREEZE_SHA256}`
- pre-reveal geometry-audit freeze: `{EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256}`
- reveal manifest SHA256: `{reveal_manifest_sha}`
- this v1 freeze SHA256: `{freeze_sha}`

## Version boundary
Any smoothing, gap filling, confidence-filter retuning, automatic geometry adoption, or merge logic is outside v1 and requires a new version plus separate validation.
"""
    report_path = out / REPORT_NAME
    write_text(report_path, report)

    output_files = [index_path, freeze_path, report_path]
    output_hashes = {
        p.name: {"path": str(p), "sha256": sha256_file(p), "bytes": int(p.stat().st_size)}
        for p in output_files
    }
    manifest = {
        "schema_version": "akerpuls-preliminary-geometry-v1-freeze-manifest",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "preliminary_geometry_v1_freeze_sha256": freeze_sha,
        "p95_fields": EXPECTED_P95,
        "prelim_2026_split_proposal": EXPECTED_LINE_AVAILABLE,
        "no_geometry_proposal": EXPECTED_NO_INTERFACE,
        "output_hashes": output_hashes,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "smoothing": False,
        "gap_filling": False,
        "merge_executed": False,
        "official_2025_geometry_replaced": False,
        "automatic_geometry_mutation": False,
    }
    write_json(out / MANIFEST_NAME, manifest)

    print("AKERPULS PRELIMINARY GEOMETRY V1 FREEZE")
    print(f"STATUS={STATUS}")
    print(f"PARENT_D2C_FREEZE_SHA256={EXPECTED_D2C_FREEZE_SHA256}")
    print(f"P95_PROPOSAL_FREEZE_SHA256={EXPECTED_PROPOSAL_FREEZE_SHA256}")
    print(f"GEOMETRY_AUDIT_FREEZE_SHA256={EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256}")
    print(f"P95_FIELDS={EXPECTED_P95} PRELIM_2026_SPLIT_PROPOSAL={EXPECTED_LINE_AVAILABLE} NO_GEOMETRY_PROPOSAL={EXPECTED_NO_INTERFACE}")
    print(f"FIRST_BLIND_P95_SPLIT_STRICT={EXPECTED_FIRST_AUDIT_P95_STRICT}/{EXPECTED_FIRST_AUDIT_P95_N} FIRST_BLIND_P95_SPLIT_BROAD={EXPECTED_FIRST_AUDIT_P95_BROAD}/{EXPECTED_FIRST_AUDIT_P95_N}")
    print(f"GEOMETRY_LINE_STRICT={EXPECTED_LINE_STRICT_ON_SPLIT}/{EXPECTED_GEOM_SPLIT_POSITIVE} GEOMETRY_LINE_BROAD={EXPECTED_LINE_BROAD_ON_SPLIT}/{EXPECTED_GEOM_SPLIT_POSITIVE} GEOMETRY_LINE_WRONG={EXPECTED_LINE_WRONG_ON_SPLIT}/{EXPECTED_GEOM_SPLIT_POSITIVE}")
    print("CANONICAL_GEOMETRY=OFFICIAL_2025_GEOMETRY PROPOSAL_ONLY=TRUE")
    print("SMOOTHING=FALSE GAP_FILLING=FALSE MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE MERGE_EXECUTED=FALSE")
    print("OFFICIAL_2025_GEOMETRY_REPLACED=FALSE AUTOMATIC_GEOMETRY_MUTATION=FALSE")
    print(f"PRELIMINARY_GEOMETRY_V1_FREEZE_SHA256={freeze_sha}")
    print("NEXT=DOWNSTREAM_USE_AS_REVIEW_ONLY_PRELIMINARY_2026_GEOMETRY")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
