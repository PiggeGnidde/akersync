#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT E · candidate feature validation.

E is diagnostic only:
- no combined score,
- no frozen component percentile,
- no hidden weighting.

It compares field-weighted and unit-weighted behavior, redundancy, directional
agreement and extreme-set stability within each candidate family.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_e.json"
KEY = ["blockid", "skiftesbeteckning"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)


def resolve_alias(columns: list[str], aliases: list[str]) -> str | None:
    exact = {str(c).lower(): str(c) for c in columns}
    for a in aliases:
        if a.lower() in exact:
            return exact[a.lower()]
    return None


def candidate_inventory(
    frames: dict[str, pd.DataFrame],
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, dict[str, dict[str, Any]]]]:
    rows = []
    resolved: dict[str, dict[str, dict[str, Any]]] = {}

    # Candidate source priority. Local physical inputs live in merged field frame;
    # groundwater history in gw units; surface history in sw units.
    family_sources = {
        "MarkTorka": "fields",
        "MarkVata": "fields",
        "GrundvattenTillgang": "fields",
        "GrundvattenTorka": "gw_units",
        "YtvattenTorka": "sw_units",
    }

    for family, specs in cfg["candidates"].items():
        source = family_sources[family]
        df = frames[source]
        resolved[family] = {}
        for spec in specs:
            col = resolve_alias(list(df.columns), list(spec["aliases"]))
            required = bool(spec.get("required", False))
            direction = int(spec["direction"])
            if col is None:
                rows.append({
                    "family": family,
                    "candidate": spec["name"],
                    "source": source,
                    "column": None,
                    "direction": direction,
                    "required": required,
                    "n": 0,
                    "coverage_pct": 0.0,
                    "status": "MISSING_REQUIRED" if required else "MISSING_OPTIONAL",
                })
                continue

            x = numeric(df[col])
            coverage = 100.0 * x.notna().mean()
            rows.append({
                "family": family,
                "candidate": spec["name"],
                "source": source,
                "column": col,
                "direction": direction,
                "required": required,
                "n": int(x.notna().sum()),
                "coverage_pct": float(coverage),
                "status": "AVAILABLE",
            })
            resolved[family][spec["name"]] = {
                "column": col,
                "direction": direction,
                "required": required,
                "source": source,
            }

    return pd.DataFrame(rows), resolved


def describe_candidate(
    df: pd.DataFrame,
    family: str,
    candidate: str,
    col: str,
    weighting: str,
) -> dict[str, Any]:
    x = numeric(df[col]).dropna()
    out = {
        "family": family,
        "candidate": candidate,
        "column": col,
        "weighting": weighting,
        "n": int(len(x)),
        "missing_pct": float(100.0 * (1.0 - len(x) / len(df))) if len(df) else None,
    }
    if x.empty:
        for k in ("mean","std","min","p01","p10","p25","p50","p75","p90","p99","max"):
            out[k] = None
        return out

    qs = x.quantile([.01,.10,.25,.50,.75,.90,.99])
    out.update({
        "mean": float(x.mean()),
        "std": float(x.std()),
        "min": float(x.min()),
        "p01": float(qs.loc[.01]),
        "p10": float(qs.loc[.10]),
        "p25": float(qs.loc[.25]),
        "p50": float(qs.loc[.50]),
        "p75": float(qs.loc[.75]),
        "p90": float(qs.loc[.90]),
        "p99": float(qs.loc[.99]),
        "max": float(x.max()),
    })
    return out


def oriented_series(df: pd.DataFrame, col: str, direction: int) -> pd.Series:
    x = numeric(df[col])
    return x * int(direction)


def pair_diagnostics(
    df: pd.DataFrame,
    family: str,
    candidates: dict[str, dict[str, Any]],
    top_fraction: float,
) -> pd.DataFrame:
    names = list(candidates)
    rows = []
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            a, b = names[i], names[j]
            sa = oriented_series(df, candidates[a]["column"], candidates[a]["direction"])
            sb = oriented_series(df, candidates[b]["column"], candidates[b]["direction"])
            q = pd.DataFrame({"a":sa,"b":sb}).dropna()
            if len(q) < 3:
                rho = np.nan
                overlap = np.nan
                n_top_a = n_top_b = n_inter = 0
            else:
                rho = float(q["a"].corr(q["b"], method="spearman"))
                ra = q["a"].rank(method="average", pct=True)
                rb = q["b"].rank(method="average", pct=True)
                ta = set(q.index[ra >= 1.0-top_fraction])
                tb = set(q.index[rb >= 1.0-top_fraction])
                n_top_a, n_top_b = len(ta), len(tb)
                n_inter = len(ta & tb)
                overlap = n_inter / min(n_top_a, n_top_b) if min(n_top_a,n_top_b) else np.nan

            rows.append({
                "family":family,
                "candidate_a":a,
                "candidate_b":b,
                "n_pair":int(len(q)),
                "spearman_oriented":rho,
                "top_fraction":top_fraction,
                "top_n_a":n_top_a,
                "top_n_b":n_top_b,
                "top_intersection":n_inter,
                "top_overlap_fraction":float(overlap) if np.isfinite(overlap) else None,
            })
    return pd.DataFrame(rows)


def family_frame(
    family: str,
    fields: pd.DataFrame,
    gw_units: pd.DataFrame,
    sw_units: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    if family in {"MarkTorka","MarkVata","GrundvattenTillgang"}:
        return fields, "field"
    if family == "GrundvattenTorka":
        return gw_units, "unit"
    if family == "YtvattenTorka":
        return sw_units, "unit"
    raise KeyError(family)


def unit_weighted_stats_for_field_candidates(
    fields: pd.DataFrame,
    resolved: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """For history-derived field columns, compare unit and field weighting.

    This function is intentionally only used for families whose unit identity is
    frozen in C/D; local soil/TWI candidates do not have a natural hydrological
    unit-weighted counterpart.
    """
    rows: list[dict[str, Any]] = []
    return rows


def history_field_weighted_stats(
    d_fields: pd.DataFrame,
    resolved: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows = []
    for family in ("GrundvattenTorka","YtvattenTorka"):
        for candidate, meta in resolved.get(family, {}).items():
            col = meta["column"]
            if col in d_fields.columns:
                rows.append(describe_candidate(
                    d_fields, family, candidate, col, "field_weighted"
                ))
    return rows


def quantile_shift_table(stats: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (family,candidate), q in stats.groupby(["family","candidate"]):
        a = q[q["weighting"].eq("field_weighted")]
        b = q[q["weighting"].eq("unit_weighted")]
        if len(a) != 1 or len(b) != 1:
            continue
        ra, rb = a.iloc[0], b.iloc[0]
        rows.append({
            "family":family,
            "candidate":candidate,
            "field_p10":ra["p10"],
            "unit_p10":rb["p10"],
            "field_p50":ra["p50"],
            "unit_p50":rb["p50"],
            "field_p90":ra["p90"],
            "unit_p90":rb["p90"],
            "median_shift_field_minus_unit": (
                float(ra["p50"] - rb["p50"])
                if pd.notna(ra["p50"]) and pd.notna(rb["p50"]) else None
            ),
        })
    return pd.DataFrame(rows)


def extremes(
    df: pd.DataFrame,
    family: str,
    candidate: str,
    meta: dict[str, Any],
    n_tail: int,
) -> pd.DataFrame:
    col = meta["column"]
    direction = int(meta["direction"])
    q = df.copy()
    q["_oriented"] = oriented_series(q, col, direction)
    q = q[q["_oriented"].notna()].copy()
    if q.empty:
        return pd.DataFrame()

    identifiers = [
        c for c in (
            "blockid","skiftesbeteckning","kommun","omrade_id","ARO_UUID","Subid"
        ) if c in q.columns
    ]
    keep = identifiers + [col,"_oriented"]
    hi = q.nlargest(n_tail, "_oriented")[keep].copy()
    hi["tail"] = "directional_high"
    hi["rank_within_tail"] = np.arange(1, len(hi)+1)
    lo = q.nsmallest(n_tail, "_oriented")[keep].copy()
    lo["tail"] = "directional_low"
    lo["rank_within_tail"] = np.arange(1, len(lo)+1)
    out = pd.concat([hi,lo], ignore_index=True)
    out.insert(0, "candidate", candidate)
    out.insert(0, "family", family)
    return out.drop(columns="_oriented")


def cross_family_field_corr(
    fields: pd.DataFrame,
    resolved: dict[str, dict[str, dict[str, Any]]],
) -> pd.DataFrame:
    cols = {}
    meta_map = {}
    for family, fam in resolved.items():
        for candidate, meta in fam.items():
            col = meta["column"]
            if col not in fields.columns:
                continue
            key = f"{family}::{candidate}"
            cols[key] = oriented_series(fields, col, meta["direction"])
            meta_map[key] = (family,candidate)
    if len(cols) < 2:
        return pd.DataFrame()

    z = pd.DataFrame(cols)
    corr = z.corr(method="spearman")
    rows = []
    names = list(corr.columns)
    for i in range(len(names)):
        for j in range(i+1,len(names)):
            a,b = names[i],names[j]
            fa,ca = meta_map[a]
            fb,cb = meta_map[b]
            if fa == fb:
                continue
            rows.append({
                "family_a":fa,"candidate_a":ca,
                "family_b":fb,"candidate_b":cb,
                "spearman_oriented":float(corr.loc[a,b]) if pd.notna(corr.loc[a,b]) else None,
            })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()
    cfg = read_json(Path(args.config))
    work = ROOT / cfg["output"]["work_dir"]
    work.mkdir(parents=True, exist_ok=True)

    print("="*124)
    print("ÅkerVatten MVP v0a · STOPPUNKT E · CANDIDATE FEATURE VALIDATION")
    print("="*124)
    print("Diagnostic only: no combined score and no component percentile is frozen.")

    print("\n[1/7] Load frozen D + local physical features")
    d_fields = pd.read_parquet(ROOT / cfg["paths"]["d_fields"])
    gw_units = pd.read_parquet(ROOT / cfg["paths"]["d_groundwater_units"])
    sw_units = pd.read_parquet(ROOT / cfg["paths"]["d_surface_units"])
    soil = pd.read_csv(
        cfg["paths"]["soil"],
        dtype={"blockid":str,"skiftesbeteckning":str},
        low_memory=False,
    )
    hydro = pd.read_csv(
        cfg["paths"]["hydrology"],
        dtype={"blockid":str,"skiftesbeteckning":str},
        low_memory=False,
    )
    for frame,name in ((d_fields,"D fields"),(soil,"soil"),(hydro,"hydrology")):
        if frame[KEY].duplicated().any():
            raise RuntimeError(f"{name} has duplicate field keys")

    soil_cols = KEY + [c for c in ("sand_mean","clay_mean","silt_mean") if c in soil.columns]
    hydro_candidates = [
        c for c in hydro.columns
        if c in KEY
        or c.lower() in {"twi_mean","slope_mean","mean_slope","slope_deg_mean","slope_pct_mean"}
    ]
    fields = d_fields.merge(
        soil[soil_cols], on=KEY, how="left", validate="one_to_one", suffixes=("","_soil")
    )
    fields = fields.merge(
        hydro[hydro_candidates], on=KEY, how="left", validate="one_to_one", suffixes=("","_hydro")
    )
    print(f"  fields       : {len(fields):,}")
    print(f"  groundwater units: {len(gw_units):,}")
    print(f"  surface units    : {len(sw_units):,}")

    frames = {"fields":fields,"gw_units":gw_units,"sw_units":sw_units}

    print("\n[2/7] Candidate inventory + coverage")
    inventory, resolved = candidate_inventory(frames, cfg)
    atomic_csv(inventory, work/"e_candidate_inventory.csv")
    min_cov = 100.0 * float(cfg["validation"]["min_required_coverage"])
    problems = []
    for row in inventory.itertuples(index=False):
        req = "REQ" if row.required else "opt"
        col = row.column if row.column is not None else "-"
        print(
            f"  {row.family:23s} · {row.candidate:31s} · "
            f"{req:3s} · {row.coverage_pct:7.3f}% · {col}"
        )
        if row.required and (row.status != "AVAILABLE" or row.coverage_pct < min_cov):
            problems.append(
                f"required candidate {row.family}/{row.candidate} "
                f"coverage={row.coverage_pct:.3f}% status={row.status}"
            )

    print("\n[3/7] Field-weighted and unit-weighted distributions")
    stat_rows = []
    for family,fam in resolved.items():
        df, weighting_base = family_frame(family, fields, gw_units, sw_units)
        for candidate,meta in fam.items():
            stat_rows.append(describe_candidate(
                df, family, candidate, meta["column"],
                "unit_weighted" if weighting_base == "unit" else "field_weighted"
            ))
    stat_rows.extend(history_field_weighted_stats(fields, resolved))
    stats = pd.DataFrame(stat_rows)
    atomic_csv(stats, work/"e_candidate_distributions.csv")
    shifts = quantile_shift_table(stats)
    atomic_csv(shifts, work/"e_history_field_vs_unit_quantile_shift.csv")

    if len(shifts):
        print("  history field-vs-unit median shifts:")
        for r in shifts.itertuples(index=False):
            print(
                f"    {r.family:20s} {r.candidate:31s} · "
                f"field P50={r.field_p50:.5g} · unit P50={r.unit_p50:.5g} · "
                f"shift={r.median_shift_field_minus_unit:.5g}"
            )

    print("\n[4/7] Within-family redundancy and extreme-set stability")
    pair_parts = []
    red_rho = float(cfg["validation"]["redundancy_abs_spearman"])
    red_top = float(cfg["validation"]["redundancy_top_overlap"])
    top_fraction = float(cfg["validation"]["top_fraction"])
    for family,fam in resolved.items():
        df,_ = family_frame(family, fields, gw_units, sw_units)
        pairs = pair_diagnostics(df, family, fam, top_fraction)
        pair_parts.append(pairs)
        if len(pairs):
            print(f"  {family}:")
            for r in pairs.itertuples(index=False):
                rho = "NA" if r.spearman_oriented is None or pd.isna(r.spearman_oriented) else f"{r.spearman_oriented:+.3f}"
                ov = "NA" if r.top_overlap_fraction is None or pd.isna(r.top_overlap_fraction) else f"{r.top_overlap_fraction:.3f}"
                flag = (
                    "  REDUNDANCY?"
                    if (
                        (r.spearman_oriented is not None and pd.notna(r.spearman_oriented) and abs(r.spearman_oriented) >= red_rho)
                        or (r.top_overlap_fraction is not None and pd.notna(r.top_overlap_fraction) and r.top_overlap_fraction >= red_top)
                    )
                    else ""
                )
                print(
                    f"    {r.candidate_a:28s} vs {r.candidate_b:28s} · "
                    f"rho={rho} · top10 overlap={ov}{flag}"
                )
    pairs_all = pd.concat(pair_parts, ignore_index=True) if pair_parts else pd.DataFrame()
    atomic_csv(pairs_all, work/"e_within_family_pair_diagnostics.csv")

    print("\n[5/7] Cross-family directional correlations")
    cross = cross_family_field_corr(fields, resolved)
    atomic_csv(cross, work/"e_cross_family_spearman.csv")
    if len(cross):
        q = cross.copy()
        q["_abs"] = pd.to_numeric(q["spearman_oriented"], errors="coerce").abs()
        q = q.sort_values("_abs", ascending=False).head(12)
        for r in q.itertuples(index=False):
            print(
                f"  {r.family_a}/{r.candidate_a} ↔ "
                f"{r.family_b}/{r.candidate_b}: rho={r.spearman_oriented:+.3f}"
            )

    print("\n[6/7] Directional extremes for map/manual sanity checks")
    ex_parts = []
    n_tail = int(cfg["validation"]["extremes_per_tail"])
    for family,fam in resolved.items():
        df,_ = family_frame(family, fields, gw_units, sw_units)
        for candidate,meta in fam.items():
            ex = extremes(df, family, candidate, meta, n_tail)
            if len(ex):
                ex_parts.append(ex)
    ex_all = pd.concat(ex_parts, ignore_index=True) if ex_parts else pd.DataFrame()
    atomic_csv(ex_all, work/"e_directional_extremes.csv")
    print(f"  extreme rows written: {len(ex_all):,}")

    print("\n[7/7] Validation summary")
    redundancy_flags = []
    if len(pairs_all):
        for r in pairs_all.itertuples(index=False):
            rho_flag = (
                r.spearman_oriented is not None and pd.notna(r.spearman_oriented)
                and abs(r.spearman_oriented) >= red_rho
            )
            top_flag = (
                r.top_overlap_fraction is not None and pd.notna(r.top_overlap_fraction)
                and r.top_overlap_fraction >= red_top
            )
            if rho_flag or top_flag:
                redundancy_flags.append({
                    "family":r.family,
                    "candidate_a":r.candidate_a,
                    "candidate_b":r.candidate_b,
                    "spearman_oriented":(
                        float(r.spearman_oriented)
                        if r.spearman_oriented is not None and pd.notna(r.spearman_oriented)
                        else None
                    ),
                    "top_overlap_fraction":(
                        float(r.top_overlap_fraction)
                        if r.top_overlap_fraction is not None and pd.notna(r.top_overlap_fraction)
                        else None
                    ),
                })

    status = "PASS_WITH_REVIEW" if not problems else "FAIL"
    summary = {
        "schema_version":"akervatten-mvp-v0a-e-feature-validation-result",
        "status":status,
        "required_candidate_problems":problems,
        "redundancy_flags":redundancy_flags,
        "resolved_candidates":resolved,
        "guardrails":cfg["guardrails"],
        "outputs":{
            "inventory":str(work/"e_candidate_inventory.csv"),
            "distributions":str(work/"e_candidate_distributions.csv"),
            "history_field_vs_unit":str(work/"e_history_field_vs_unit_quantile_shift.csv"),
            "within_family_pairs":str(work/"e_within_family_pair_diagnostics.csv"),
            "cross_family_spearman":str(work/"e_cross_family_spearman.csv"),
            "directional_extremes":str(work/"e_directional_extremes.csv"),
        },
    }
    atomic_json(work/"e_summary.json", summary)

    print(f"  required-candidate problems: {len(problems)}")
    print(f"  redundancy flags          : {len(redundancy_flags)}")
    print("  status                    :", status)
    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -", p)

    print("\nOutputs:", work)
    print("="*124)
    print(f"AKERVATTEN STOPPUNKT E FEATURE VALIDATION: {status}")
    print("No component score or combined score has been frozen.")
    print("="*124)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
