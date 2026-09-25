#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerFrö – Ärter MVP v0a · C7 rotation eligibility + predecessor study.

Part A: rotation/eligibility scenario diagnostics for candidate year 2026.
Part B: t-1 / t-2 predecessor enrichment before clean historical CONSERVART
events, matched within target year x municipality x SKO x current-area decile.

This study is deliberately downstream of frozen ÄrtMatch v0a and does not
modify any frozen ÄrtMatch file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.build_history import (  # noqa: E402
    load_config as load_base_config,
    load_frozen_summary,
    municipality_dirs,
)
from analysis.akerfro_ertor_v0a.crop_groups import (  # noqa: E402
    CONSERVART,
    FABA_BEAN,
    OTHER_PEA,
    normalize_crop_name,
)

DEFAULT_BASE_CONFIG = ROOT / "config" / "akerfro_ertor_v0a.json"
DEFAULT_C7_CONFIG = ROOT / "config" / "akerfro_ertor_c7.json"
DEFAULT_AKERMINNE_ROOT = ROOT.parent / "AkerSync-Minne"
DEFAULT_HISTORY_ROOT = ROOT / "data" / "derived" / "akerfro_ertor_v0a"
DEFAULT_CONTEXT = ROOT / "work" / "akerfro_ertor_v0a" / "controlled_profile_c2" / "field_control_context.parquet"
DEFAULT_ARTMATCH = ROOT / "data" / "derived" / "akerfro_ertor_v0a" / "artmatch_v0a_fields.parquet"
DEFAULT_OUT = ROOT / "work" / "akerfro_ertor_v0a" / "rotation_predecessor_c7"

RANDOM_SALT = "akerfro-ertor-c7-v0a"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(value: str) -> str:
    return hashlib.sha256((RANDOM_SALT + "|" + value).encode("utf-8")).hexdigest()


def last_year_by_group(summary: pd.DataFrame, group: str) -> pd.Series:
    q = summary[
        summary["is_clean"]
        & summary["akerfro_group"].eq(group)
    ]
    if q.empty:
        return pd.Series(dtype="Int64")
    return q.groupby("current_field_id")["history_year"].max().astype("Int64")


def years_since(candidate_year: int, last_year: pd.Series) -> pd.Series:
    x = pd.to_numeric(last_year, errors="coerce")
    return candidate_year - x


def eligible_from_last(candidate_year: int, last_year: pd.Series, threshold: int) -> pd.Series:
    """No observed occurrence is eligible under the observed-history scenario."""
    gap = years_since(candidate_year, last_year)
    return last_year.isna() | gap.ge(threshold)


def build_rotation_table(
    summary: pd.DataFrame,
    mixed_target: pd.DataFrame,
    artmatch: pd.DataFrame,
    candidate_year: int,
    thresholds: list[int],
) -> pd.DataFrame:
    current = (
        summary.sort_values(["current_field_id", "history_year"], kind="mergesort")
        .groupby("current_field_id", sort=True)
        .tail(1)[["current_field_id", "municipality"]]
        .drop_duplicates("current_field_id")
        .set_index("current_field_id")
    )

    last_target_clean = last_year_by_group(summary, CONSERVART)
    last_other_pea = last_year_by_group(summary, OTHER_PEA)
    last_faba = last_year_by_group(summary, FABA_BEAN)

    any_target_parts = []
    clean_target = summary[
        summary["is_clean"] & summary["akerfro_group"].eq(CONSERVART)
    ][["current_field_id", "history_year"]]
    if len(clean_target):
        any_target_parts.append(clean_target)
    if len(mixed_target):
        q = mixed_target[["current_field_id", "history_year"]].drop_duplicates()
        any_target_parts.append(q)
    any_target = pd.concat(any_target_parts, ignore_index=True).drop_duplicates()
    last_target_any = (
        any_target.groupby("current_field_id")["history_year"].max().astype("Int64")
        if len(any_target) else pd.Series(dtype="Int64")
    )

    out = current.copy()
    out["last_conservart_clean_year"] = last_target_clean
    out["last_conservart_any_component_year"] = last_target_any
    out["last_other_pea_clean_year"] = last_other_pea
    out["last_faba_bean_clean_year"] = last_faba

    out["last_any_pea_clean_year"] = pd.concat(
        [last_target_clean.rename("target"), last_other_pea.rename("other")],
        axis=1,
    ).max(axis=1, skipna=True)
    out["last_pea_or_faba_clean_year"] = pd.concat(
        [
            last_target_clean.rename("target"),
            last_other_pea.rename("other"),
            last_faba.rename("faba"),
        ],
        axis=1,
    ).max(axis=1, skipna=True)

    for source in [
        "conservart_clean",
        "conservart_any_component",
        "other_pea_clean",
        "faba_bean_clean",
        "any_pea_clean",
        "pea_or_faba_clean",
    ]:
        last_col = "last_" + source + "_year"
        if last_col not in out.columns:
            # aliases above already follow exact naming except composite columns
            continue
        out["years_since_" + source] = years_since(candidate_year, out[last_col])

    # Explicit aliases for readability / stable output schema.
    out["years_since_conservart_clean"] = years_since(candidate_year, out["last_conservart_clean_year"])
    out["years_since_conservart_any_component"] = years_since(candidate_year, out["last_conservart_any_component_year"])
    out["years_since_other_pea_clean"] = years_since(candidate_year, out["last_other_pea_clean_year"])
    out["years_since_faba_bean_clean"] = years_since(candidate_year, out["last_faba_bean_clean_year"])
    out["years_since_any_pea_clean"] = years_since(candidate_year, out["last_any_pea_clean_year"])
    out["years_since_pea_or_faba_clean"] = years_since(candidate_year, out["last_pea_or_faba_clean_year"])

    scenario_sources = {
        "target_clean": "last_conservart_clean_year",
        "target_any_component": "last_conservart_any_component_year",
        "any_pea_clean": "last_any_pea_clean_year",
        "pea_or_faba_clean": "last_pea_or_faba_clean_year",
    }
    for threshold in thresholds:
        for label, col in scenario_sources.items():
            out[f"eligible_{label}_{threshold}y"] = eligible_from_last(
                candidate_year, out[col], threshold
            ).astype(bool)

    out["history_left_censored_2015"] = True
    out["candidate_year"] = candidate_year
    out = out.reset_index()

    if artmatch is not None and len(artmatch):
        keep = [
            c for c in [
                "current_field_id", "artmatch_score", "artmatch_status",
                "artmatch_slope_component", "artmatch_akerscore_component",
                "artmatch_texture_component",
            ] if c in artmatch.columns
        ]
        out = out.merge(
            artmatch[keep],
            on="current_field_id",
            how="left",
            validate="one_to_one",
        )
    return out


def eligibility_summary(rotation: pd.DataFrame, thresholds: list[int]) -> pd.DataFrame:
    rows = []
    for threshold in thresholds:
        for scenario in [
            "target_clean", "target_any_component", "any_pea_clean", "pea_or_faba_clean"
        ]:
            col = f"eligible_{scenario}_{threshold}y"
            n = int(rotation[col].sum())
            rows.append({
                "threshold_years": threshold,
                "scenario": scenario,
                "eligible_fields": n,
                "eligible_pct": 100.0 * n / len(rotation),
                "ineligible_fields": int(len(rotation) - n),
            })
    return pd.DataFrame(rows)


def normalize_crop_series(s: pd.Series) -> pd.Series:
    return s.map(normalize_crop_name).astype("string")


def make_lagged_events(
    summary: pd.DataFrame,
    context: pd.DataFrame,
    lag: int,
) -> pd.DataFrame:
    base = summary[[
        "history_year", "current_field_id", "municipality",
        "dominant_crop_name", "status", "is_clean", "akerfro_group",
    ]].copy()
    pred = base[[
        "history_year", "current_field_id", "dominant_crop_name", "status", "is_clean",
    ]].copy()
    pred["history_year"] = pred["history_year"] + lag
    pred = pred.rename(columns={
        "dominant_crop_name": "predecessor_crop_name",
        "status": "predecessor_status",
        "is_clean": "predecessor_is_clean",
    })

    events = base.merge(
        pred,
        on=["history_year", "current_field_id"],
        how="left",
        validate="one_to_one",
    )
    ctx = context[[
        "current_field_id", "dominant_sko_id_c2", "area_decile"
    ]].drop_duplicates("current_field_id")
    events = events.merge(
        ctx, on="current_field_id", how="left", validate="many_to_one"
    )
    events["predecessor_crop_key"] = normalize_crop_series(events["predecessor_crop_name"])
    events["match_stratum"] = (
        events["history_year"].astype("string")
        + "|" + events["municipality"].astype("string")
        + "|" + events["dominant_sko_id_c2"].astype("string")
        + "|A" + events["area_decile"].astype("string")
    )
    return events


def matched_predecessor_sample(
    events: pd.DataFrame,
    controls_per_positive: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = (
        events["is_clean"]
        & events["predecessor_is_clean"].fillna(False)
        & events["predecessor_crop_key"].notna()
        & events["predecessor_crop_key"].ne("")
        & events["dominant_sko_id_c2"].notna()
        & events["area_decile"].notna()
    )
    work = events[valid].copy()
    work["is_target_event"] = work["akerfro_group"].eq(CONSERVART)

    parts = []
    diag = []
    for stratum, g in work.groupby("match_stratum", sort=True):
        pos = g[g["is_target_event"]].copy()
        ctl = g[~g["is_target_event"]].copy()
        if pos.empty or ctl.empty:
            if not pos.empty:
                diag.append({
                    "match_stratum": str(stratum),
                    "n_positive": len(pos),
                    "n_controls_available": len(ctl),
                    "n_controls_selected": 0,
                    "status": "NO_COMMON_SUPPORT",
                })
            continue
        target_n = min(len(ctl), controls_per_positive * len(pos))
        ctl["_order"] = ctl.apply(
            lambda r: stable_hash(
                f"{r['current_field_id']}|{int(r['history_year'])}|{stratum}"
            ),
            axis=1,
        )
        ctl = ctl.sort_values("_order", kind="mergesort").head(target_n).drop(columns="_order")
        pos["sample_role"] = "positive"
        ctl["sample_role"] = "matched_control"
        parts.extend([pos, ctl])
        diag.append({
            "match_stratum": str(stratum),
            "n_positive": len(pos),
            "n_controls_available": len(g) - len(pos),
            "n_controls_selected": len(ctl),
            "status": "MATCHED",
        })

    if not parts:
        raise RuntimeError("C7 predecessor matching found no common-support events")
    return pd.concat(parts, ignore_index=True), pd.DataFrame(diag)


def crop_display_lookup(sample: pd.DataFrame) -> dict[str, str]:
    q = sample[["predecessor_crop_key", "predecessor_crop_name"]].dropna().copy()
    out = {}
    for key, g in q.groupby("predecessor_crop_key", sort=True):
        counts = g["predecessor_crop_name"].astype(str).value_counts()
        out[str(key)] = str(counts.index[0])
    return out


def enrichment_table(sample: pd.DataFrame, lag: int) -> pd.DataFrame:
    pos = sample[sample["sample_role"].eq("positive")]
    ctl = sample[sample["sample_role"].eq("matched_control")]
    n_pos = len(pos)
    n_ctl = len(ctl)
    display = crop_display_lookup(sample)
    keys = sorted(set(pos["predecessor_crop_key"].dropna()) | set(ctl["predecessor_crop_key"].dropna()))
    rows = []
    for key in keys:
        a = int(pos["predecessor_crop_key"].eq(key).sum())
        b = int(ctl["predecessor_crop_key"].eq(key).sum())
        pp = a / n_pos if n_pos else np.nan
        pc = b / n_ctl if n_ctl else np.nan
        enrichment = pp / pc if pc > 0 else np.inf
        rows.append({
            "lag_years": lag,
            "crop_key": str(key),
            "crop_name": display.get(str(key), str(key)),
            "positive_count": a,
            "positive_pct": 100.0 * pp,
            "control_count": b,
            "control_pct": 100.0 * pc,
            "difference_pp": 100.0 * (pp - pc),
            "enrichment_ratio": enrichment,
            "log2_enrichment": math.log2(enrichment) if np.isfinite(enrichment) and enrichment > 0 else np.nan,
        })
    return pd.DataFrame(rows).sort_values(
        ["positive_count", "enrichment_ratio"],
        ascending=[False, False],
        kind="mergesort",
    ).reset_index(drop=True)


def by_target_year(sample: pd.DataFrame, lag: int) -> pd.DataFrame:
    rows = []
    for (year, role, crop), g in sample.groupby(
        ["history_year", "sample_role", "predecessor_crop_key"], sort=True
    ):
        rows.append({
            "lag_years": lag,
            "target_year": int(year),
            "sample_role": role,
            "crop_key": crop,
            "n_events": int(len(g)),
        })
    return pd.DataFrame(rows)


def make_sequence_events(
    summary: pd.DataFrame,
    context: pd.DataFrame,
) -> pd.DataFrame:
    e1 = make_lagged_events(summary, context, 1)
    pred2 = summary[[
        "history_year", "current_field_id", "dominant_crop_name", "is_clean"
    ]].copy()
    pred2["history_year"] = pred2["history_year"] + 2
    pred2 = pred2.rename(columns={
        "dominant_crop_name": "predecessor2_crop_name",
        "is_clean": "predecessor2_is_clean",
    })
    e = e1.merge(
        pred2,
        on=["history_year", "current_field_id"],
        how="left",
        validate="one_to_one",
    )
    e["predecessor2_crop_key"] = normalize_crop_series(e["predecessor2_crop_name"])
    e["sequence_key"] = (
        e["predecessor2_crop_key"].fillna("")
        + " -> "
        + e["predecessor_crop_key"].fillna("")
    )
    e["predecessor_is_clean"] = (
        e["predecessor_is_clean"].fillna(False)
        & e["predecessor2_is_clean"].fillna(False)
    )
    e.loc[
        e["predecessor2_crop_key"].isna() | e["predecessor2_crop_key"].eq(""),
        "predecessor_crop_key"
    ] = pd.NA
    # Reuse matcher using sequence as the "crop".
    e["predecessor_crop_key"] = e["sequence_key"].where(
        e["predecessor_crop_key"].notna(), pd.NA
    )
    e["predecessor_crop_name"] = e["predecessor_crop_key"]
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", default=str(DEFAULT_BASE_CONFIG))
    ap.add_argument("--c7-config", default=str(DEFAULT_C7_CONFIG))
    ap.add_argument("--akerminne-root", default=str(DEFAULT_AKERMINNE_ROOT))
    ap.add_argument("--history-root", default=str(DEFAULT_HISTORY_ROOT))
    ap.add_argument("--context", default=str(DEFAULT_CONTEXT))
    ap.add_argument("--artmatch", default=str(DEFAULT_ARTMATCH))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    base_cfg = load_base_config(Path(args.base_config))
    cfg = load_json(Path(args.c7_config))
    candidate_year = int(cfg["candidate_year"])
    thresholds = [int(x) for x in cfg["rotation_gap_scenarios_years"]]
    controls_per_positive = int(cfg["controls_per_positive"])

    dirs = municipality_dirs(Path(args.akerminne_root), base_cfg)
    history = load_frozen_summary(dirs, base_cfg)

    history_root = Path(args.history_root)
    mixed_path = history_root / "pea_mixed_or_complex_target_field_years.parquet"
    if not mixed_path.exists():
        raise FileNotFoundError("Run STOPPUNKT B first; mixed target history is missing")
    mixed_target = pd.read_parquet(mixed_path)

    context = pd.read_parquet(Path(args.context))
    if len(context) != 128636:
        raise RuntimeError(f"C7 expected 128,636 field context rows; got {len(context):,}")
    artmatch = pd.read_parquet(Path(args.artmatch)) if Path(args.artmatch).exists() else pd.DataFrame()

    rotation = build_rotation_table(
        history, mixed_target, artmatch, candidate_year, thresholds
    )
    if len(rotation) != 128636:
        raise RuntimeError(f"C7 expected 128,636 rotation rows; got {len(rotation):,}")
    elig_summary = eligibility_summary(rotation, thresholds)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rotation_path = out / f"rotation_eligibility_{candidate_year}.parquet"
    rotation_csv_path = out / f"rotation_eligibility_{candidate_year}.csv"
    elig_summary_path = out / "rotation_eligibility_summary.csv"
    rotation.to_parquet(rotation_path, index=False)
    rotation.to_csv(rotation_csv_path, index=False, encoding="utf-8-sig")
    elig_summary.to_csv(elig_summary_path, index=False, encoding="utf-8-sig")

    lag_reports = {}
    for lag in [int(x) for x in cfg["predecessor_lags"]]:
        events = make_lagged_events(history, context, lag)
        sample, diag = matched_predecessor_sample(events, controls_per_positive)
        enrich = enrichment_table(sample, lag)
        yearly = by_target_year(sample, lag)

        sample_path = out / f"predecessor_lag{lag}_matched_sample.parquet"
        enrich_path = out / f"predecessor_lag{lag}_enrichment.csv"
        diag_path = out / f"predecessor_lag{lag}_matching_diagnostics.csv"
        yearly_path = out / f"predecessor_lag{lag}_by_target_year.csv"
        sample.to_parquet(sample_path, index=False)
        enrich.to_csv(enrich_path, index=False, encoding="utf-8-sig")
        diag.to_csv(diag_path, index=False, encoding="utf-8-sig")
        yearly.to_csv(yearly_path, index=False, encoding="utf-8-sig")

        lag_reports[str(lag)] = {
            "positive_events": int(sample["sample_role"].eq("positive").sum()),
            "matched_controls": int(sample["sample_role"].eq("matched_control").sum()),
            "matched_strata": int(diag["status"].eq("MATCHED").sum()),
            "positive_target_year_min": int(sample.loc[sample["sample_role"].eq("positive"), "history_year"].min()),
            "positive_target_year_max": int(sample.loc[sample["sample_role"].eq("positive"), "history_year"].max()),
            "outputs": {
                "sample": str(sample_path),
                "enrichment": str(enrich_path),
                "matching_diagnostics": str(diag_path),
                "by_target_year": str(yearly_path),
            },
        }

    seq_events = make_sequence_events(history, context)
    seq_sample, seq_diag = matched_predecessor_sample(seq_events, controls_per_positive)
    seq_enrich = enrichment_table(seq_sample, 2).rename(columns={
        "crop_key": "sequence_key",
        "crop_name": "sequence",
    })
    seq_path = out / "predecessor_sequence_tminus2_to_tminus1_enrichment.csv"
    seq_diag_path = out / "predecessor_sequence_matching_diagnostics.csv"
    seq_enrich.to_csv(seq_path, index=False, encoding="utf-8-sig")
    seq_diag.to_csv(seq_diag_path, index=False, encoding="utf-8-sig")

    report = {
        "schema_version": "akerfro-ertor-rotation-predecessor-c7-v0a",
        "candidate_year": candidate_year,
        "history_years": [2015, 2025],
        "current_fields": int(len(rotation)),
        "rotation_threshold_scenarios": thresholds,
        "eligibility_basis": {
            "target_clean": "clean SINGLE_CROP CONSERVART only",
            "target_any_component": "clean CONSERVART plus mixed/complex field-years containing a CONSERVART component",
            "any_pea_clean": "clean CONSERVART or OTHER_PEA",
            "pea_or_faba_clean": "clean CONSERVART or OTHER_PEA or FABA_BEAN",
        },
        "predecessor_matching": cfg["matching_stratum"],
        "controls_per_positive_target": controls_per_positive,
        "predecessor_lags": lag_reports,
        "sequence_positive_events": int(seq_sample["sample_role"].eq("positive").sum()),
        "guardrails": cfg["guardrails"],
        "artmatch_frozen_unchanged": True,
        "outputs": {
            "rotation": str(rotation_path),
            "rotation_summary": str(elig_summary_path),
            "sequence_enrichment": str(seq_path),
        },
    }
    summary_path = out / "c7_summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 126)
    print("ÅkerFrö – Ärter MVP v0a · C7 ROTATION ELIGIBILITY + PREDECESSOR STUDY")
    print("=" * 126)
    print(f"Candidate year: {candidate_year} · current fields: {len(rotation):,}")
    print("ÄrtMatch v0a: READ-ONLY / unchanged")

    print("\nROTATION ELIGIBILITY SCENARIOS")
    print(elig_summary.to_string(index=False, formatters={
        "eligible_pct": lambda v: f"{v:.2f}%"
    }))

    for lag in sorted(lag_reports, key=int):
        enrich = pd.read_csv(out / f"predecessor_lag{lag}_enrichment.csv")
        info = lag_reports[lag]
        print(f"\nT-{lag} PREDECESSOR: {info['positive_events']:,} positive events · {info['matched_controls']:,} controls")
        common = enrich.sort_values("positive_count", ascending=False).head(15)
        print("MOST COMMON BEFORE CONSERVÄRT")
        print(common[[
            "crop_name", "positive_count", "positive_pct", "control_count",
            "control_pct", "difference_pp", "enrichment_ratio"
        ]].to_string(index=False, formatters={
            "positive_pct": lambda v: f"{v:.2f}%",
            "control_pct": lambda v: f"{v:.2f}%",
            "difference_pp": lambda v: f"{v:+.2f}",
            "enrichment_ratio": lambda v: f"{v:.2f}x",
        }))

        robust = enrich[enrich["positive_count"] >= 10].copy()
        print("\nENRICHED (>=10 positive events)")
        print(robust.sort_values(
            ["enrichment_ratio", "positive_count"], ascending=[False, False]
        ).head(10)[[
            "crop_name", "positive_count", "positive_pct", "control_pct",
            "difference_pp", "enrichment_ratio"
        ]].to_string(index=False, formatters={
            "positive_pct": lambda v: f"{v:.2f}%",
            "control_pct": lambda v: f"{v:.2f}%",
            "difference_pp": lambda v: f"{v:+.2f}",
            "enrichment_ratio": lambda v: f"{v:.2f}x",
        }))

        print("\nDEPLETED (>=10 positive events)")
        print(robust.sort_values(
            ["enrichment_ratio", "positive_count"], ascending=[True, False]
        ).head(10)[[
            "crop_name", "positive_count", "positive_pct", "control_pct",
            "difference_pp", "enrichment_ratio"
        ]].to_string(index=False, formatters={
            "positive_pct": lambda v: f"{v:.2f}%",
            "control_pct": lambda v: f"{v:.2f}%",
            "difference_pp": lambda v: f"{v:+.2f}",
            "enrichment_ratio": lambda v: f"{v:.2f}x",
        }))

    print("\nTOP T-2 -> T-1 SEQUENCES (>=8 positive events)")
    seq_show = seq_enrich[seq_enrich["positive_count"] >= 8].sort_values(
        ["positive_count", "enrichment_ratio"], ascending=[False, False]
    ).head(20)
    print(seq_show[[
        "sequence", "positive_count", "positive_pct", "control_pct",
        "difference_pp", "enrichment_ratio"
    ]].to_string(index=False, formatters={
        "positive_pct": lambda v: f"{v:.2f}%",
        "control_pct": lambda v: f"{v:.2f}%",
        "difference_pp": lambda v: f"{v:+.2f}",
        "enrichment_ratio": lambda v: f"{v:.2f}x",
    }))

    print("\nGUARDRAILS")
    for x in cfg["guardrails"]:
        print("  - " + x)

    print(f"\nRotation table: {rotation_path}")
    print(f"Eligibility summary: {elig_summary_path}")
    print(f"T-1 enrichment: {out / 'predecessor_lag1_enrichment.csv'}")
    print(f"T-2 enrichment: {out / 'predecessor_lag2_enrichment.csv'}")
    print(f"Sequence enrichment: {seq_path}")
    print(f"Summary: {summary_path}")
    print("=" * 126)
    print("C7 ROTATION + PREDECESSOR STUDY: PASS")
    print("=" * 126)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
