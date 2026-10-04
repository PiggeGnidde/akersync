#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build ÅkerFrö Rotation v1.1 candidate as a downstream product.

Frozen ÅkerFrö v0a/C8 remains read-only. The only allowed class change is:
C_ROTATION_CAUTION -> A/B when the CONSERVART caution is proven to consist
entirely of strict historical-boundary spill and no other recent pea/faba
signal remains.

No API calls. No frozen files modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "akerfro_rotation_v1a.json"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerfro_rotation_v1a"
DEFAULT_WORK = ROOT / "work" / "akerfro_rotation_v1a"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def discover_c8(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise FileNotFoundError(p)
    rel = Path("data/derived/akerfro_ertor_v0a/artkandidat_v0a_fields.parquet")
    candidates = [
        ROOT / rel,
        ROOT.parent / "AkerSync-AkerFro" / rel,
        Path(r"C:\AkerSync-AkerFro") / rel,
        Path(r"C:\AkerSyncRepo") / rel,
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("Could not auto-discover frozen artkandidat_v0a_fields.parquet")


def discover_minne_root(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            return p
        raise FileNotFoundError(p)
    candidates = [
        ROOT.parent / "AkerSync-Minne",
        Path(r"C:\AkerSync-Minne"),
        Path(r"C:\AkerSyncRepo-Minne"),
    ]
    for p in candidates:
        d = p / "data" / "derived" / "akerminne_v1a" / "skane" / "municipalities"
        if d.is_dir():
            return p
    raise FileNotFoundError("Could not auto-discover frozen ÅkerMinne Skåne root")


def recent_year(series: pd.Series, lo: int, hi: int) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    return x.between(lo, hi, inclusive="both").fillna(False).astype(bool)


def conservart_mask(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.lower().str.contains("konserv", regex=False)


def load_recent_conservart_components(minne_root: Path, lo: int, hi: int) -> tuple[pd.DataFrame, int]:
    mroot = minne_root / "data" / "derived" / "akerminne_v1a" / "skane" / "municipalities"
    dirs = sorted(p for p in mroot.iterdir() if p.is_dir())
    if len(dirs) != 33:
        raise RuntimeError(f"Expected 33 ÅkerMinne municipality dirs; got {len(dirs)}")
    cols = [
        "municipality", "history_year", "current_field_id",
        "historical_field_id", "historical_block_id", "historical_skiftesbeteckning",
        "crop_name", "intersection_m2", "share_current", "share_historical",
        "same_admin_key", "is_current_primary", "is_historical_primary", "is_mutual_primary",
    ]
    parts: list[pd.DataFrame] = []
    for d in dirs:
        path = d / "akerminne_components.parquet"
        if not path.is_file():
            raise FileNotFoundError(path)
        q = pd.read_parquet(path, columns=cols)
        year = pd.to_numeric(q["history_year"], errors="coerce")
        q = q[year.between(lo, hi, inclusive="both") & conservart_mask(q["crop_name"])].copy()
        if len(q):
            parts.append(q)
    if not parts:
        raise RuntimeError("No recent CONSERVART components found in frozen ÅkerMinne")
    out = pd.concat(parts, ignore_index=True)
    out["current_field_id"] = out["current_field_id"].astype(str)
    out["historical_field_id"] = out["historical_field_id"].astype(str)
    for c in ["intersection_m2", "share_current", "share_historical"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    return out, len(dirs)


def build_product(c8: pd.DataFrame, components: pd.DataFrame, policy: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    anchors = policy["expected_anchors"]
    if len(c8) != int(anchors["population_fields"]):
        raise RuntimeError(f"C8 population drift: {len(c8):,}")
    if c8["current_field_id"].duplicated().any():
        raise RuntimeError("C8 has duplicate current_field_id")
    c8 = c8.copy()
    c8["current_field_id"] = c8["current_field_id"].astype(str)

    lo, hi = int(policy["recent_year_min"]), int(policy["recent_year_max"])
    no_clean_cons = ~recent_year(c8["last_conservart_clean_year"], lo, hi)
    target = (
        c8["artkandidat_class"].astype(str).eq("C_ROTATION_CAUTION")
        & c8["rotation_status"].astype(str).eq("CAUTION_RECENT_CONSERVART")
        & no_clean_cons
    )
    target_ids = set(c8.loc[target, "current_field_id"])

    key = ["history_year", "historical_field_id"]
    dominant = (
        components.sort_values(
            ["history_year", "historical_field_id", "share_historical", "intersection_m2"],
            ascending=[True, True, False, False], kind="mergesort"
        )
        .groupby(key, as_index=False).first()
        [key + ["current_field_id", "share_historical", "intersection_m2"]]
        .rename(columns={
            "current_field_id": "dominant_current_field_id",
            "share_historical": "dominant_historical_share",
            "intersection_m2": "dominant_intersection_m2",
        })
    )
    tx = components[components["current_field_id"].isin(target_ids)].merge(
        dominant, on=key, how="left", validate="many_to_one"
    )
    if tx.empty:
        raise RuntimeError("No recent CONSERVART lineage rows found for candidate C fields")

    scfg = policy["strict_boundary_spill"]
    dom_min = float(scfg["other_current_field_historical_share_min"])
    this_max = float(scfg["this_current_field_historical_share_max_exclusive"])

    def boolcol(name: str) -> pd.Series:
        return tx[name].fillna(False).astype(bool)

    tx["strict_boundary_spill"] = (
        tx["current_field_id"].ne(tx["dominant_current_field_id"])
        & tx["dominant_historical_share"].ge(dom_min)
        & tx["share_historical"].lt(this_max)
        & ~boolcol("same_admin_key")
        & ~boolcol("is_historical_primary")
        & ~boolcol("is_mutual_primary")
    )

    agg = (
        tx.groupby("current_field_id", as_index=False)
        .agg(
            boundary_component_rows=("historical_field_id", "size"),
            all_recent_conservart_components_strict_spill=("strict_boundary_spill", "all"),
            any_recent_conservart_component_strict_spill=("strict_boundary_spill", "any"),
            max_this_historical_share=("share_historical", "max"),
            max_this_current_share=("share_current", "max"),
            max_intersection_m2=("intersection_m2", "max"),
            min_dominant_historical_share=("dominant_historical_share", "min"),
        )
    )

    out = c8.merge(agg, on="current_field_id", how="left", validate="one_to_one")
    out["boundary_component_rows"] = pd.to_numeric(out["boundary_component_rows"], errors="coerce").fillna(0).astype(int)
    for c in [
        "all_recent_conservart_components_strict_spill",
        "any_recent_conservart_component_strict_spill",
    ]:
        out[c] = out[c].fillna(False).astype(bool)

    recent_other = recent_year(out["last_other_pea_clean_year"], lo, hi)
    recent_faba = recent_year(out["last_faba_bean_clean_year"], lo, hi)
    out["rotation_v1a_recent_other_pea"] = recent_other
    out["rotation_v1a_recent_faba"] = recent_faba

    target_after_merge = (
        out["artkandidat_class"].astype(str).eq("C_ROTATION_CAUTION")
        & out["rotation_status"].astype(str).eq("CAUTION_RECENT_CONSERVART")
        & ~recent_year(out["last_conservart_clean_year"], lo, hi)
    )
    out["rotation_v1a_release_candidate"] = (
        target_after_merge
        & out["all_recent_conservart_components_strict_spill"]
        & ~recent_other
        & ~recent_faba
    )

    out["rotation_status_v0a"] = out["rotation_status"].astype("string")
    out["artkandidat_class_v0a"] = out["artkandidat_class"].astype("string")
    out["rotation_status_v1a"] = out["rotation_status_v0a"].copy()
    out["artkandidat_class_v1a"] = out["artkandidat_class_v0a"].copy()
    out["rotation_v1a_evidence"] = "UNCHANGED_FROM_V0A"

    released = out["rotation_v1a_release_candidate"]
    positive_pred = out["predecessor_prior"].astype(str).eq("POSITIVE")
    out.loc[released, "rotation_status_v1a"] = "ROTATION_OK_BOUNDARY_SPILL"
    out.loc[released, "rotation_v1a_evidence"] = "STRICT_LINEAGE_BOUNDARY_SPILL"
    out.loc[released & positive_pred, "artkandidat_class_v1a"] = "A_STRONG_CANDIDATE"
    out.loc[released & ~positive_pred, "artkandidat_class_v1a"] = "B_PHYSICAL_CANDIDATE"

    out["artkandidat_reason_v1a"] = out["artkandidat_reason"].astype("string")
    out.loc[released, "artkandidat_reason_v1a"] = (
        "high ÄrtMatch; v0a CONSERVART caution released because every recent target component "
        "is strict lineage boundary spill; no recent other pea/faba remains; predecessor prior then determines A/B"
    )

    release_cols = [
        "current_field_id", "municipality", "artkandidat_class_v0a", "artkandidat_class_v1a",
        "rotation_status_v0a", "rotation_status_v1a", "rotation_v1a_evidence",
        "predecessor_prior", "crop_2025_name", "artmatch_score",
        "boundary_component_rows", "max_this_historical_share", "max_this_current_share",
        "max_intersection_m2", "min_dominant_historical_share",
        "rotation_v1a_recent_other_pea", "rotation_v1a_recent_faba",
    ]
    release_table = out.loc[released, [c for c in release_cols if c in out.columns]].copy()
    return out, release_table


def validate_anchors(product: pd.DataFrame, release: pd.DataFrame, policy: dict[str, Any]) -> dict[str, Any]:
    a = policy["expected_anchors"]
    orig = product["artkandidat_class_v0a"].value_counts().to_dict()
    new = product["artkandidat_class_v1a"].value_counts().to_dict()
    if {k: int(orig.get(k, 0)) for k in a["original_class_counts"]} != a["original_class_counts"]:
        raise RuntimeError(f"Original C8 class-count anchor drift: {orig}")
    if {k: int(new.get(k, 0)) for k in a["v1a_class_counts"]} != a["v1a_class_counts"]:
        raise RuntimeError(f"v1.1 class-count anchor drift: {new}")

    lo, hi = int(policy["recent_year_min"]), int(policy["recent_year_max"])
    target = (
        product["artkandidat_class_v0a"].astype(str).eq("C_ROTATION_CAUTION")
        & product["rotation_status_v0a"].astype(str).eq("CAUTION_RECENT_CONSERVART")
        & ~recent_year(product["last_conservart_clean_year"], lo, hi)
    )
    strict = target & product["all_recent_conservart_components_strict_spill"]
    blocked = strict & (product["rotation_v1a_recent_other_pea"] | product["rotation_v1a_recent_faba"])
    checks = {
        "c_conservart_no_recent_clean_fields": int(target.sum()),
        "all_recent_components_strict_spill_fields": int(strict.sum()),
        "strict_spill_blocked_by_other_pea_or_faba": int(blocked.sum()),
        "released_fields": int(len(release)),
        "released_to_A": int(release["artkandidat_class_v1a"].eq("A_STRONG_CANDIDATE").sum()),
        "released_to_B": int(release["artkandidat_class_v1a"].eq("B_PHYSICAL_CANDIDATE").sum()),
    }
    for k, got in checks.items():
        exp = int(a[k])
        if got != exp:
            raise RuntimeError(f"Anchor {k}: expected {exp}, got {got}")
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=str(DEFAULT_POLICY))
    ap.add_argument("--c8")
    ap.add_argument("--akerminne-root")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    args = ap.parse_args()

    policy = load_json(Path(args.policy))
    c8_path = discover_c8(args.c8)
    minne_root = discover_minne_root(args.akerminne_root)
    c8 = pd.read_parquet(c8_path)
    components, nmun = load_recent_conservart_components(
        minne_root, int(policy["recent_year_min"]), int(policy["recent_year_max"])
    )

    product, release = build_product(c8, components, policy)
    checks = validate_anchors(product, release, policy)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    work = Path(args.work); work.mkdir(parents=True, exist_ok=True)
    product_path = out / "akerfro_rotation_v1a_fields.parquet"
    release_path = out / "akerfro_rotation_v1a_released_fields.csv"
    summary_path = out / "akerfro_rotation_v1a_summary.json"
    lineage_path = work / "released_lineage_components.csv"

    product.to_parquet(product_path, index=False)
    release.to_csv(release_path, index=False, encoding="utf-8-sig")

    release_ids = set(release["current_field_id"].astype(str))
    rel_lineage = components[components["current_field_id"].isin(release_ids)].copy()
    rel_lineage.to_csv(lineage_path, index=False, encoding="utf-8-sig")

    summary = {
        "schema_version": policy["schema_version"],
        "status": "CANDIDATE_PRODUCT_NOT_FROZEN",
        "inputs": {
            "frozen_c8": str(c8_path),
            "frozen_akerminne_root": str(minne_root),
        },
        "municipalities_scanned": nmun,
        "policy": policy,
        "verified_anchors": checks,
        "class_counts_v0a": {str(k): int(v) for k, v in product["artkandidat_class_v0a"].value_counts().items()},
        "class_counts_v1a": {str(k): int(v) for k, v in product["artkandidat_class_v1a"].value_counts().items()},
        "outputs": {
            "field_product": str(product_path),
            "released_fields": str(release_path),
            "released_lineage_components": str(lineage_path),
        },
        "guardrails": policy["semantic_guardrails"],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 118)
    print("ÅkerFrö Rotation v1.1 · DOWNSTREAM CANDIDATE PRODUCT")
    print("=" * 118)
    print(f"Frozen C8: {c8_path}")
    print(f"ÅkerMinne: {minne_root} · municipalities {nmun}")
    print(f"Fields: {len(product):,}")
    print(f"Released C -> A/B: {len(release):,} = A {checks['released_to_A']:,} + B {checks['released_to_B']:,}")
    print("v1.1 class counts:")
    print(product["artkandidat_class_v1a"].value_counts().to_string())
    print(f"Product: {product_path}")
    print(f"Released: {release_path}")
    print(f"Summary: {summary_path}")
    print("=" * 118)
    print("AKERFRO ROTATION V1.1 BUILD: PASS")
    print("=" * 118)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
