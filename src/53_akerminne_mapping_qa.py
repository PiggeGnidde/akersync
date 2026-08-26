#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STOPPUNKT B QA: diagnose overlap anomalies before full ÅkerMinne history processing."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import normalize, union_all

from common import load_config, sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
DEFAULT_PROJECT_LOCAL = ROOT / "config" / "local_paths.json"
DEFAULT_MAPPING = ROOT / "data" / "derived" / "akerminne_v1a" / "mapping_prototype"
DEFAULT_OUT = ROOT / "data" / "derived" / "akerminne_v1a" / "mapping_qa"
AREA_EPS_M2 = 1e-6


def field_key(frame: pd.DataFrame) -> pd.Series:
    return frame["blockid"].astype(str) + "|" + frame["skiftesbeteckning"].astype(str)


def read_region(path: Path, code: str) -> gpd.GeoDataFrame:
    try:
        g = gpd.read_file(path, where=f"CAST(region_kod AS TEXT) LIKE '{code}%'")
        if len(g):
            return g
    except Exception:
        pass
    g = gpd.read_file(path)
    if "region_kod" not in g.columns:
        raise RuntimeError(f"region_kod saknas i {path}")
    return g[g["region_kod"].astype(str).str.startswith(code)].copy()


def read_current(project_cfg: dict[str, Any], code: str) -> gpd.GeoDataFrame:
    spath = Path(project_cfg["skiften"])
    try:
        return read_region(spath, code)
    except RuntimeError:
        bpath = Path(project_cfg["blocks"])
        blocks = read_region(bpath, code)
        allowed = set(blocks["blockid"].astype(str))
        g = gpd.read_file(spath, bbox=tuple(float(v) for v in blocks.total_bounds))
        return g[g["blockid"].astype(str).isin(allowed)].copy()


def historical_path(raw_root: Path, year: int) -> Path:
    return raw_root / "akerminne_v1a" / str(year) / f"arslager_skifte_skurup_{year}.gpkg"


def prepare(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    required = {"blockid", "skiftesbeteckning", "geometry"}
    missing = sorted(required - set(gdf.columns))
    if missing:
        raise ValueError(f"saknar kolumner {missing}")
    if gdf.crs is None or gdf.crs.to_epsg() != 3006:
        raise ValueError(f"förväntade EPSG:3006, fick {gdf.crs}")
    g = gdf.copy().reset_index(drop=True)
    g["field_key"] = field_key(g)
    g["area_m2"] = g.geometry.area.astype(float)
    return g


def exact_duplicate_geometry_summary(g: gpd.GeoDataFrame) -> dict[str, Any]:
    sigs = [None if geom is None or geom.is_empty else normalize(geom).wkb_hex for geom in g.geometry]
    s = pd.Series(sigs, index=g.index, dtype="object")
    groups = s.dropna().groupby(s.dropna()).groups
    dup_groups = [list(idx) for idx in groups.values() if len(idx) > 1]
    return {
        "duplicate_geometry_groups": int(len(dup_groups)),
        "rows_in_duplicate_geometry_groups": int(sum(len(x) for x in dup_groups)),
        "examples": [[str(g.at[i, "field_key"]) for i in idxs[:10]] for idxs in dup_groups[:10]],
    }


def self_overlap_summary(g: gpd.GeoDataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    base = g[(g.geometry.notna()) & (~g.geometry.is_empty) & (g["area_m2"] > 0)].copy()
    cand = gpd.sjoin(base[["geometry"]], base[["geometry"]], how="inner", predicate="intersects")
    cand = cand.reset_index().rename(columns={"index": "left_idx", "index_right": "right_idx"})
    cand = cand[cand["left_idx"] < cand["right_idx"]]
    rows = []
    for r in cand.itertuples(index=False):
        i, j = int(r.left_idx), int(r.right_idx)
        inter = base.at[i, "geometry"].intersection(base.at[j, "geometry"])
        area = float(inter.area) if inter is not None and not inter.is_empty else 0.0
        if area <= AREA_EPS_M2:
            continue
        ai, aj = float(base.at[i, "area_m2"]), float(base.at[j, "area_m2"])
        rows.append({
            "field_a": str(base.at[i, "field_key"]), "field_b": str(base.at[j, "field_key"]),
            "block_a": str(base.at[i, "blockid"]), "block_b": str(base.at[j, "blockid"]),
            "intersection_m2": area, "fraction_a": area / ai, "fraction_b": area / aj,
            "min_fraction": min(area / ai, area / aj), "max_fraction": max(area / ai, area / aj),
            "same_block": bool(str(base.at[i, "blockid"]) == str(base.at[j, "blockid"])),
        })
    pairs = pd.DataFrame(rows)
    if pairs.empty:
        return {"positive_pairs": 0, "gt_1m2": 0, "min_fraction_gt_0_01": 0, "min_fraction_gt_0_50": 0,
                "min_fraction_gt_0_90": 0, "same_block_pairs": 0, "different_block_pairs": 0,
                "intersection_m2_total": 0.0}, pairs
    pairs = pairs.sort_values(["intersection_m2", "field_a", "field_b"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)
    return {
        "positive_pairs": int(len(pairs)), "gt_1m2": int((pairs["intersection_m2"] > 1.0).sum()),
        "min_fraction_gt_0_01": int((pairs["min_fraction"] > 0.01).sum()),
        "min_fraction_gt_0_50": int((pairs["min_fraction"] > 0.50).sum()),
        "min_fraction_gt_0_90": int((pairs["min_fraction"] > 0.90).sum()),
        "same_block_pairs": int(pairs["same_block"].sum()), "different_block_pairs": int((~pairs["same_block"]).sum()),
        "intersection_m2_total": float(pairs["intersection_m2"].sum()),
        "max_intersection_m2": float(pairs["intersection_m2"].max()), "max_min_fraction": float(pairs["min_fraction"].max()),
    }, pairs


def anomaly_union_diagnostics(current: gpd.GeoDataFrame, historical: gpd.GeoDataFrame, matches: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    cur = prepare(current).set_index("field_key", drop=False)
    hist = prepare(historical).set_index("field_key", drop=False)
    rows = []
    for mr in matches[matches["coverage_raw"] > 1.000001].itertuples(index=False):
        ck = str(mr.current_field_id)
        if ck not in cur.index:
            continue
        cgeom, carea = cur.at[ck, "geometry"], float(cur.at[ck, "area_m2"])
        raw = edges[edges["current_field_key"].astype(str) == ck].copy()
        intersections, hist_keys = [], []
        for er in raw.itertuples(index=False):
            hk = str(er.historical_field_key)
            if hk not in hist.index:
                continue
            inter = cgeom.intersection(hist.at[hk, "geometry"])
            if inter is not None and not inter.is_empty and inter.area > AREA_EPS_M2:
                intersections.append(inter); hist_keys.append(hk)
        union_geom = union_all(intersections) if intersections else None
        union_area = float(union_geom.area) if union_geom is not None and not union_geom.is_empty else 0.0
        sum_area = float(raw["intersection_m2"].sum()) if len(raw) else 0.0
        exact_dup_neighbors = 0
        for i in range(len(hist_keys)):
            for j in range(i + 1, len(hist_keys)):
                if normalize(hist.at[hist_keys[i], "geometry"]).equals_exact(normalize(hist.at[hist_keys[j], "geometry"]), tolerance=0.0):
                    exact_dup_neighbors += 1
        rows.append({
            "current_field_id": ck, "match_confidence": str(mr.match_confidence),
            "positive_overlap_edges": int(mr.positive_overlap_edges), "qualifying_relaxed_edges": int(mr.qualifying_relaxed_edges),
            "coverage_raw": float(mr.coverage_raw), "coverage_union": union_area / carea if carea > 0 else 0.0,
            "excess_coverage": (sum_area - union_area) / carea if carea > 0 else 0.0,
            "sum_intersection_m2": sum_area, "union_intersection_m2": union_area,
            "exact_duplicate_neighbor_pairs": int(exact_dup_neighbors), "historical_neighbor_count": int(len(set(hist_keys))),
        })
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["excess_coverage", "coverage_raw", "current_field_id"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    return out


def status_summary(matches: pd.DataFrame) -> dict[str, Any]:
    counts = {str(k): int(v) for k, v in matches["match_confidence"].value_counts().sort_index().items()}
    n = int(len(matches))
    secure = sum(counts.get(k, 0) for k in ("direct_id", "one_to_one_strict", "one_to_one_relaxed"))
    topology = sum(counts.get(k, 0) for k in ("split", "merge"))
    unresolved = sum(counts.get(k, 0) for k in ("ambiguous", "unmatched"))
    return {"counts": counts, "secure_1to1": secure, "secure_1to1_fraction": secure / n if n else 0.0,
            "split_merge": topology, "split_merge_fraction": topology / n if n else 0.0,
            "ambiguous_unmatched": unresolved, "ambiguous_unmatched_fraction": unresolved / n if n else 0.0}


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = ["# ÅkerMinne v1a – STOPPUNKT B overlap QA", "", f"Generated: `{report['generated_at_utc']}`", "",
             "Purpose: diagnose `coverage_raw > 1` before full 2015–2025 processing.", "",
             "`coverage_union` is the geometric union of all historical intersections with one 2025 field and therefore cannot exceed 1 (apart from floating-point tolerance).",
             "`excess_coverage = coverage_raw - coverage_union` measures double-counted historical overlap.", "",
             "## Summary", "",
             "| Year | secure 1:1 | split+merge | ambiguous+unmatched | anomalies raw>1 | anomaly union>1 | hist self-overlap pairs | >50% mutual overlap | exact duplicate geometry groups | duplicate admin-key rows |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for year, r in report["years"].items():
        s, h, a = r["status"], r["historical_layer"], r["anomalies"]
        lines.append(f"| {year} | {s['secure_1to1']} ({s['secure_1to1_fraction']:.1%}) | {s['split_merge']} ({s['split_merge_fraction']:.1%}) | {s['ambiguous_unmatched']} ({s['ambiguous_unmatched_fraction']:.1%}) | {a['count']} | {a['coverage_union_gt_1_count']} | {h['self_overlap']['positive_pairs']} | {h['self_overlap']['min_fraction_gt_0_50']} | {h['exact_duplicate_geometry']['duplicate_geometry_groups']} | {h['duplicate_admin_key_rows']} |")
    lines += ["", "## Detail by year", ""]
    for year, r in report["years"].items():
        h, a = r["historical_layer"], r["anomalies"]
        lines += [f"### {year}", "", f"- Historical rows: `{h['rows']}`", f"- Duplicate admin-key rows: `{h['duplicate_admin_key_rows']}`",
                  f"- Exact duplicate geometry groups: `{h['exact_duplicate_geometry']['duplicate_geometry_groups']}`; rows in such groups: `{h['exact_duplicate_geometry']['rows_in_duplicate_geometry_groups']}`",
                  f"- Historical self-overlap positive pairs: `{h['self_overlap']['positive_pairs']}`; >1 m²: `{h['self_overlap']['gt_1m2']}`; min overlap fraction >50%: `{h['self_overlap']['min_fraction_gt_0_50']}`; >90%: `{h['self_overlap']['min_fraction_gt_0_90']}`",
                  f"- Same-block / different-block overlapping pairs: `{h['self_overlap'].get('same_block_pairs',0)}` / `{h['self_overlap'].get('different_block_pairs',0)}`",
                  f"- `coverage_raw > 1` current fields: `{a['count']}`", f"- `coverage_union > 1.000001` current fields: `{a['coverage_union_gt_1_count']}`",
                  f"- Median/max excess coverage among anomalies: `{a['excess_coverage_median']:.6f}` / `{a['excess_coverage_max']:.6f}`",
                  f"- Anomalies with exact-duplicate historical neighbor pair: `{a['with_exact_duplicate_neighbor_pair']}`", ""]
        if a.get("top_examples"):
            lines += ["Top anomaly examples:", ""]
            for ex in a["top_examples"][:10]:
                lines.append(f"- `{ex['current_field_id']}`: status `{ex['match_confidence']}`, raw `{ex['coverage_raw']:.4f}`, union `{ex['coverage_union']:.4f}`, excess `{ex['excess_coverage']:.4f}`, historical neighbors `{ex['historical_neighbor_count']}`")
            lines.append("")
    lines += ["## Guardrail", "", "This QA does not change matching thresholds or classifications. Review the source-overlap findings before continuing to full history processing.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG)); ap.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT_LOCAL)); ap.add_argument("--mapping-dir", default=str(DEFAULT_MAPPING))
    ap.add_argument("--output", default=str(DEFAULT_OUT)); ap.add_argument("--years", default="2015,2020")
    args = ap.parse_args()
    cfg, local_cfg, project_cfg = load_config(args.config), load_config(args.local_config), load_config(args.project_local_config)
    years = [int(x.strip()) for x in args.years.split(",") if x.strip()]
    code, raw_root, mapping_dir, outdir = str(cfg["pilot_municipality_code"]), Path(local_cfg["raw_root"]), Path(args.mapping_dir), Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    current = prepare(read_current(project_cfg, code))
    current_overlap, _ = self_overlap_summary(current); current_dups = exact_duplicate_geometry_summary(current)
    report: dict[str, Any] = {"schema_version": "akerminne-mapping-qa-v1a", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "municipality": str(cfg["pilot_municipality"]), "municipality_code": code, "reference_year": int(cfg["reference_year"]),
        "current_layer": {"rows": int(len(current)), "duplicate_admin_key_rows": int(current.duplicated("field_key", keep=False).sum()),
                          "exact_duplicate_geometry": current_dups, "self_overlap": current_overlap}, "years": {}}
    print("=" * 78); print("ÅkerMinne v1a · STOPPUNKT B overlap QA"); print("=" * 78)
    print(f"Current 2025: {len(current):,} fields; self-overlap pairs={current_overlap['positive_pairs']:,}; exact duplicate geometry groups={current_dups['duplicate_geometry_groups']:,}")
    for year in years:
        hpath = historical_path(raw_root, year); mp = mapping_dir / str(year) / "current_matches.parquet"; ep = mapping_dir / str(year) / "pair_overlaps.parquet"
        for p in (hpath, mp, ep):
            if not p.exists(): raise FileNotFoundError(p)
        hist = prepare(read_region(hpath, code)); matches = pd.read_parquet(mp); edges = pd.read_parquet(ep)
        h_overlap, h_pairs = self_overlap_summary(hist); h_dups = exact_duplicate_geometry_summary(hist)
        diag = anomaly_union_diagnostics(current, hist, matches, edges)
        ydir = outdir / str(year); ydir.mkdir(parents=True, exist_ok=True)
        diag_path = ydir / "coverage_anomalies.parquet"; pair_path = ydir / "historical_self_overlaps.parquet"
        diag.to_parquet(diag_path, index=False); h_pairs.to_parquet(pair_path, index=False)
        n = int(len(diag))
        a = {"count": n, "coverage_union_gt_1_count": int((diag["coverage_union"] > 1.000001).sum()) if n else 0,
             "excess_coverage_median": float(diag["excess_coverage"].median()) if n else 0.0,
             "excess_coverage_max": float(diag["excess_coverage"].max()) if n else 0.0,
             "with_exact_duplicate_neighbor_pair": int((diag["exact_duplicate_neighbor_pairs"] > 0).sum()) if n else 0,
             "top_examples": diag.head(10).to_dict(orient="records") if n else [], "coverage_anomalies_path": str(diag_path),
             "coverage_anomalies_sha256": sha256_file(diag_path)}
        report["years"][str(year)] = {"status": status_summary(matches), "historical_layer": {"path": str(hpath), "rows": int(len(hist)),
            "duplicate_admin_key_rows": int(hist.duplicated("field_key", keep=False).sum()), "exact_duplicate_geometry": h_dups, "self_overlap": h_overlap,
            "self_overlaps_path": str(pair_path), "self_overlaps_sha256": sha256_file(pair_path)}, "anomalies": a}
        print("-" * 78); print(f"{year}: hist={len(hist):,}; self-overlap pairs={h_overlap['positive_pairs']:,}; >50%={h_overlap['min_fraction_gt_0_50']:,}; exact duplicate geometry groups={h_dups['duplicate_geometry_groups']:,}")
        print(f"{year}: raw>1 anomalies={n:,}; union>1={a['coverage_union_gt_1_count']:,}; median/max excess={a['excess_coverage_median']:.6f}/{a['excess_coverage_max']:.6f}")
    jpath, mpath = outdir / "mapping_qa_report.json", outdir / "mapping_qa_report.md"
    jpath.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"); write_markdown(report, mpath)
    print("=" * 78); print("MAPPING QA: PASS"); print("=" * 78); print("Report:", mpath); print("STOPPUNKT B remains active: review QA before Phase 3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
