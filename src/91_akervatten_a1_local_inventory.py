#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT A1 local reuse inventory.

Audits existing Skåne soil/hydrology/water exploratory artifacts.
A1 defines no new product score and downloads no SGU/SMHI data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_a1.json"
DEFAULT_WORK = ROOT / "work" / "akervatten_mvp_v0a" / "a1_local_inventory"

KEY_CANDIDATES = [
    ("current_field_id",),
    ("blockid", "skiftesbeteckning"),
    ("block_id", "skifte_id"),
]

NUMERIC_INTEREST = [
    "area_ha",
    "clay_mean", "sand_mean", "silt_mean",
    "clay_coverage_pct", "sand_coverage_pct", "silt_coverage_pct",
    "clay_n_pix", "sand_n_pix", "silt_n_pix",
    "twi_mean", "twi_p50", "twi_p90", "twi_n_cells",
    "wetness_pctile", "dryness_pctile",
    "drainage_challenge_score", "irrigation_sensitivity_score",
    "texture_axis", "wetness_axis", "water_regime_strength",
    "slope_mean_deg", "slope_p90_deg", "relief_p95_p05_m",
    "local_low50_lt_m0p25_pct", "local_low50_lt_m0p50_pct",
    "local_low150_lt_m0p50_pct",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(
            path,
            low_memory=False,
            dtype={
                "blockid": "string",
                "skiftesbeteckning": "string",
                "current_field_id": "string",
                "municipality": "string",
                "kommun": "string",
            },
        )
    raise ValueError(f"Unsupported input format: {path}")


def detect_key(df: pd.DataFrame) -> tuple[str, ...] | None:
    cols = set(df.columns)
    for candidate in KEY_CANDIDATES:
        if all(c in cols for c in candidate):
            return candidate
    return None


def normalize_key_frame(df: pd.DataFrame, key: tuple[str, ...]) -> pd.DataFrame:
    x = pd.DataFrame(index=df.index)
    for c in key:
        x[c] = df[c].astype("string").fillna("").str.strip()
    return x


def key_profile(name: str, df: pd.DataFrame) -> dict[str, Any]:
    key = detect_key(df)
    if key is None:
        return {
            "source": name, "key_columns": None, "rows": int(len(df)),
            "missing_key_rows": None, "duplicate_key_rows": None, "unique_keys": None,
        }
    k = normalize_key_frame(df, key)
    missing = k.eq("").any(axis=1)
    duplicates = k.duplicated(keep=False) & ~missing
    unique = k.loc[~missing].drop_duplicates()
    return {
        "source": name,
        "key_columns": list(key),
        "rows": int(len(df)),
        "missing_key_rows": int(missing.sum()),
        "duplicate_key_rows": int(duplicates.sum()),
        "unique_keys": int(len(unique)),
    }


def key_set(df: pd.DataFrame) -> tuple[tuple[str, ...] | None, set[tuple[str, ...]]]:
    key = detect_key(df)
    if key is None:
        return None, set()
    k = normalize_key_frame(df, key)
    mask = ~k.eq("").any(axis=1)
    values = {
        tuple(row)
        for row in k.loc[mask, list(key)].itertuples(index=False, name=None)
    }
    return key, values


def schema_rows(name: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    n = len(df)
    rows = []
    for c in df.columns:
        s = df[c]
        non_null = int(s.notna().sum())
        rows.append({
            "source": name,
            "column": c,
            "dtype": str(s.dtype),
            "rows": int(n),
            "non_null": non_null,
            "coverage_pct": 100.0 * non_null / n if n else np.nan,
            "n_unique_non_null": int(s.nunique(dropna=True)),
        })
    return rows


def numeric_summary_rows(name: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for c in NUMERIC_INTEREST:
        if c not in df.columns:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        valid = s[np.isfinite(s)]
        if valid.empty:
            continue
        q = valid.quantile([0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
        rows.append({
            "source": name, "column": c, "n_valid": int(valid.size),
            "coverage_pct": 100.0 * valid.size / len(df) if len(df) else np.nan,
            "min": float(valid.min()),
            "p01": float(q.loc[0.01]), "p05": float(q.loc[0.05]),
            "p10": float(q.loc[0.10]), "p25": float(q.loc[0.25]),
            "p50": float(q.loc[0.50]), "p75": float(q.loc[0.75]),
            "p90": float(q.loc[0.90]), "p95": float(q.loc[0.95]),
            "p99": float(q.loc[0.99]), "max": float(valid.max()),
        })
    return rows


def verify_old_heuristics(water: pd.DataFrame) -> dict[str, Any]:
    out = {
        "checked": False,
        "drainage_max_abs_error": None,
        "irrigation_max_abs_error": None,
        "status": "NOT_CHECKED",
    }
    needed = {
        "clay_pctile", "sand_pctile", "wetness_pctile", "dryness_pctile",
        "drainage_challenge_score", "irrigation_sensitivity_score",
    }
    if not needed.issubset(water.columns):
        out["status"] = "MISSING_COLUMNS"
        return out

    cp = pd.to_numeric(water["clay_pctile"], errors="coerce")
    sp = pd.to_numeric(water["sand_pctile"], errors="coerce")
    wp = pd.to_numeric(water["wetness_pctile"], errors="coerce")
    dp = pd.to_numeric(water["dryness_pctile"], errors="coerce")
    observed_d = pd.to_numeric(water["drainage_challenge_score"], errors="coerce")
    observed_i = pd.to_numeric(water["irrigation_sensitivity_score"], errors="coerce")

    expected_d = 100.0 * np.sqrt(cp * wp)
    expected_i = 100.0 * np.sqrt(sp * dp)

    dmask = np.isfinite(expected_d) & np.isfinite(observed_d)
    imask = np.isfinite(expected_i) & np.isfinite(observed_i)
    d_err = float(np.max(np.abs(expected_d[dmask] - observed_d[dmask]))) if dmask.any() else np.nan
    i_err = float(np.max(np.abs(expected_i[imask] - observed_i[imask]))) if imask.any() else np.nan

    out.update({
        "checked": True,
        "n_drainage_compared": int(dmask.sum()),
        "n_irrigation_compared": int(imask.sum()),
        "drainage_max_abs_error": d_err if np.isfinite(d_err) else None,
        "irrigation_max_abs_error": i_err if np.isfinite(i_err) else None,
        "status": "PASS" if d_err <= 1e-9 and i_err <= 1e-9 else "MISMATCH",
    })
    return out


def overlap_rows(tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    names = list(tables)
    rows = []
    cache = {name: key_set(df) for name, df in tables.items()}
    for i, a in enumerate(names):
        ka, sa = cache[a]
        if ka is None:
            continue
        for b in names[i + 1:]:
            kb, sb = cache[b]
            if kb is None or ka != kb:
                continue
            inter = len(sa & sb)
            union = len(sa | sb)
            rows.append({
                "source_a": a, "source_b": b, "key_columns": "+".join(ka),
                "n_a": len(sa), "n_b": len(sb), "intersection": inter, "union": union,
                "coverage_a_in_b_pct": 100.0 * inter / len(sa) if sa else np.nan,
                "coverage_b_in_a_pct": 100.0 * inter / len(sb) if sb else np.nan,
            })
    return rows


def candidate_feature_presence(cfg: dict[str, Any], tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for component, features in cfg["candidate_features"].items():
        for feature in features:
            found = [name for name, df in tables.items() if feature in df.columns]
            rows.append({
                "component": component,
                "feature": feature,
                "found_in": ";".join(found),
                "available": bool(found),
            })
    return rows


def build_report(
    manifest: dict[str, Any],
    key_profiles: list[dict[str, Any]],
    heuristic: dict[str, Any],
    overlaps: pd.DataFrame,
    presence: pd.DataFrame,
) -> str:
    lines = [
        "# ÅkerVatten MVP v0a · STOPPUNKT A1 local reuse inventory",
        "",
        "## Status",
        "",
        f"**{manifest['status']}**",
        "",
        "A1 is an audit only. No new MarkTorka or MarkVäta score has been frozen.",
        "",
        "## Input artifacts",
        "",
    ]
    for name, meta in manifest["inputs"].items():
        lines.append(
            f"- **{name}** — {meta['rows']:,} rows, {meta['columns']} columns, "
            f"{meta['bytes'] / 1024 / 1024:.1f} MB, SHA-256 {meta['sha256'][:16]}…"
        )

    lines += ["", "## Key integrity", ""]
    for p in key_profiles:
        key = "+".join(p["key_columns"]) if p["key_columns"] else "not detected"
        lines.append(
            f"- **{p['source']}** — key {key}, unique {p['unique_keys']}, "
            f"missing rows {p['missing_key_rows']}, duplicate rows {p['duplicate_key_rows']}."
        )

    lines += [
        "",
        "## Existing water heuristic reconstruction",
        "",
        f"- status: **{heuristic['status']}**",
        f"- drainage max absolute error: {heuristic.get('drainage_max_abs_error')}",
        f"- irrigation max absolute error: {heuristic.get('irrigation_max_abs_error')}",
        "",
        "PASS here means reproducible arithmetic, not agronomic validation.",
        "",
        "## Candidate reuse for new base components",
        "",
    ]
    for component in presence["component"].unique():
        q = presence[presence["component"].eq(component)]
        present = q[q["available"]]
        missing = q[~q["available"]]
        lines.append(f"### {component}")
        if len(present):
            lines.append("- available: " + ", ".join(present["feature"].tolist()))
        if len(missing):
            lines.append("- not found locally: " + ", ".join(missing["feature"].tolist()))
        lines.append("")

    if not overlaps.empty:
        lines += ["## Key overlap", ""]
        for r in overlaps.itertuples(index=False):
            lines.append(
                f"- {r.source_a} ↔ {r.source_b}: intersection {r.intersection:,}; "
                f"{r.coverage_a_in_b_pct:.2f}% of A in B, {r.coverage_b_in_a_pct:.2f}% of B in A."
            )
        lines.append("")

    lines += [
        "## Scientific guardrails",
        "",
        "- TWI is topographic wetness propensity, not observed soil moisture or actual drainage.",
        "- Modelled clay/sand/silt are texture proxies, not measured plant-available water capacity.",
        "- Existing drainage/irrigation heuristic scores are not adopted as ÅkerVatten product scores in A1.",
        "- No SGU/SMHI data are acquired in A1.",
        "",
        "## Decision after A1",
        "",
        "Use this inventory to decide which local fields can be reused for transparent MarkTorka and MarkVäta baselines, "
        "then proceed to official SGU/SMHI source inventory for groundwater and surface-water components.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--legacy-root", default=r"C:\AkerSyncRepo")
    ap.add_argument("--prestation-root", default=r"C:\AkerSync-Prestation")
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    legacy = Path(args.legacy_root)
    prestation = Path(args.prestation_root)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    input_paths = {
        "soil": legacy / cfg["inputs"]["soil"],
        "hydrology": legacy / cfg["inputs"]["hydrology"],
        "water_prospect": legacy / cfg["inputs"]["water_prospect"],
        "water_regimes": legacy / cfg["inputs"]["water_regimes"],
        "prestation_static_context": prestation / cfg["inputs"]["prestation_static_context"],
    }

    missing = [f"{name}: {path}" for name, path in input_paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("A1 missing required local inputs:\n  " + "\n  ".join(missing))

    tables = {}
    manifest_inputs = {}
    schema = []
    numeric = []
    profiles = []

    print("=" * 108)
    print("ÅkerVatten MVP v0a · STOPPUNKT A1 LOCAL REUSE INVENTORY")
    print("=" * 108)

    for name, path in input_paths.items():
        print(f"[read] {name}: {path}")
        df = read_table(path)
        tables[name] = df
        manifest_inputs[name] = {
            "path": str(path), "rows": int(len(df)), "columns": int(len(df.columns)),
            "bytes": int(path.stat().st_size), "sha256": sha256(path),
        }
        schema.extend(schema_rows(name, df))
        numeric.extend(numeric_summary_rows(name, df))
        profiles.append(key_profile(name, df))

    heuristic = verify_old_heuristics(tables["water_prospect"])
    overlap_df = pd.DataFrame(overlap_rows(tables))
    presence_df = pd.DataFrame(candidate_feature_presence(cfg, tables))

    problems = []
    for p in profiles:
        if p["source"] in {"soil", "hydrology", "water_prospect", "water_regimes"}:
            if p["key_columns"] is None:
                problems.append(f"{p['source']}: no field key detected")
            elif p["missing_key_rows"]:
                problems.append(f"{p['source']}: {p['missing_key_rows']} missing-key rows")
            elif p["duplicate_key_rows"]:
                problems.append(f"{p['source']}: {p['duplicate_key_rows']} duplicate-key rows")
    if heuristic["checked"] and heuristic["status"] != "PASS":
        problems.append("old water heuristics do not reconstruct exactly")

    status = "PASS" if not problems else "FAIL"
    manifest = {
        "schema_version": "akervatten-mvp-v0a-a1-local-inventory-result",
        "status": status,
        "inputs": manifest_inputs,
        "key_profiles": profiles,
        "old_heuristic_reconstruction": heuristic,
        "candidate_feature_presence": presence_df.to_dict(orient="records"),
        "guardrails": cfg["guardrails"],
        "problems": problems,
    }

    pd.DataFrame(schema).to_csv(work / "schema_inventory.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(numeric).to_csv(work / "numeric_summary.csv", index=False, encoding="utf-8-sig")
    overlap_df.to_csv(work / "key_overlap.csv", index=False, encoding="utf-8-sig")
    presence_df.to_csv(work / "candidate_feature_presence.csv", index=False, encoding="utf-8-sig")
    (work / "a1_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (work / "A1_LOCAL_REUSE_REPORT.md").write_text(
        build_report(manifest, profiles, heuristic, overlap_df, presence_df), encoding="utf-8"
    )

    print("\nINPUT SUMMARY")
    for name, meta in manifest_inputs.items():
        print(
            f"  {name:26s} rows={meta['rows']:>8,} cols={meta['columns']:>3} "
            f"size={meta['bytes']/1024/1024:7.1f} MB"
        )

    print("\nKEY INTEGRITY")
    for p in profiles:
        key = "+".join(p["key_columns"]) if p["key_columns"] else "NONE"
        print(
            f"  {p['source']:26s} key={key:28s} unique={str(p['unique_keys']):>8s} "
            f"missing={str(p['missing_key_rows']):>6s} dup_rows={str(p['duplicate_key_rows']):>6s}"
        )

    print("\nOLD EXPLORATORY WATER HEURISTICS")
    print(f"  status: {heuristic['status']}")
    if heuristic["checked"]:
        print(f"  drainage max abs error:   {heuristic['drainage_max_abs_error']:.3e}")
        print(f"  irrigation max abs error: {heuristic['irrigation_max_abs_error']:.3e}")

    print("\nCANDIDATE FEATURE PRESENCE")
    for component in presence_df["component"].unique():
        q = presence_df[presence_df["component"].eq(component)]
        available = q[q["available"]]["feature"].tolist()
        missing_features = q[~q["available"]]["feature"].tolist()
        print(f"  {component}:")
        print("    available:", ", ".join(available) if available else "NONE")
        print("    missing:  ", ", ".join(missing_features) if missing_features else "NONE")

    if not overlap_df.empty:
        print("\nKEY OVERLAP")
        print(overlap_df.to_string(index=False, formatters={
            "coverage_a_in_b_pct": lambda v: f"{v:.2f}%",
            "coverage_b_in_a_pct": lambda v: f"{v:.2f}%",
        }))

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  - " + p)

    print(f"\nOutputs: {work}")
    print("=" * 108)
    print(f"AKERVATTEN A1 LOCAL REUSE INVENTORY: {status}")
    print("=" * 108)
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
