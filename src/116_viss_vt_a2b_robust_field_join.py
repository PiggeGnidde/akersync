"""ÅkerKontext · VattenTryck — VT-A2b robust field↔groundwater join.

Refines VT-A2's permissive `intersects` relation for the 16 positive VISS GW
cases. For every field/case-polygon candidate it computes true polygon overlap
area and overlap fraction, plus representative-point membership. It then picks
a deterministic dominant GW body per field by maximum overlap area.

Important: groundwater bodies can be vertically layered. `dominant` is a
cartographic/product convenience, not a hydrogeological assertion that other
matched bodies are irrelevant. All non-zero overlap relations are retained.

Inputs are local outputs from VT-A1/VT-A2. No network access, no score, no legal
inference, no web changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
A1C = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1c"
A1E = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1e"
A2 = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a2"
OUT = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a2b"
KEY = ["blockid", "skiftesbeteckning"]


def load_json(p: Path):
    if not p.exists():
        raise RuntimeError(f"Missing {p}")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def norm(x):
    return "" if x is None else str(x).strip().upper()


def read_vector(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_parquet(path) if path.suffix.lower() == ".parquet" else gpd.read_file(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 88)
    print("ÅkerKontext · VattenTryck — VT-A2b robust field↔groundwater join")
    print("=" * 88)

    a2 = load_json(A2 / "summary.json")
    cases = load_json(A1E / "summary.json")
    waters = load_json(A1C / "waters.json")
    field_source = Path(a2["field_source"])
    if not field_source.exists():
        raise RuntimeError(f"VT-A2 field source no longer exists: {field_source}")

    fields = read_vector(field_source)
    if fields.crs is None:
        raise RuntimeError("Field layer has no CRS")
    fields = fields.to_crs(3006)
    if not all(c in fields.columns for c in KEY):
        raise RuntimeError(f"Field layer missing {KEY}")
    fields[KEY] = fields[KEY].astype(str)
    fields["field_id"] = fields["blockid"] + "|" + fields["skiftesbeteckning"]
    fields = fields[["field_id", "geometry"]].copy()
    fields["field_area_m2"] = fields.geometry.area
    if (fields["field_area_m2"] <= 0).any():
        raise RuntimeError("Found zero/negative-area field geometry")

    gw_path = A2 / "viss_groundwater_all.geojson"
    gw = gpd.read_file(gw_path).to_crs(3006)
    lookup = {str(c).upper(): c for c in gw.columns}
    eucol = lookup.get("EU_CD") or lookup.get("VISS_EU_CD")
    if not eucol:
        raise RuntimeError("No EU_CD/VISS_EU_CD in cached groundwater geometry")
    gw["EU_CD_N"] = gw[eucol].map(norm)
    case_ids = {norm(x) for x in cases["case_ids"]}
    gw = gw.loc[gw["EU_CD_N"].isin(case_ids), ["EU_CD_N", "geometry"]].copy()
    print(f"Positive case polygons: {len(gw):,} / expected {len(case_ids):,}")

    # Fast candidate generation. Then calculate actual polygon intersection area.
    cand = gpd.sjoin(fields[["field_id", "field_area_m2", "geometry"]], gw, how="inner", predicate="intersects")
    cand = cand.reset_index(drop=False).rename(columns={"index": "field_row"})
    gw_geom = gw.geometry
    cand["overlap_m2"] = [
        fields.geometry.iloc[int(fi)].intersection(gw_geom.loc[int(gi)]).area
        for fi, gi in zip(cand["field_row"], cand["index_right"])
    ]
    cand["overlap_fraction"] = cand["overlap_m2"] / cand["field_area_m2"]
    positive = cand[cand["overlap_m2"] > 0].copy()

    # Representative point is guaranteed inside the field polygon (unlike centroid
    # for concave polygons) and is therefore safer for a point-in-polygon diagnostic.
    reps = fields[["field_id", "geometry"]].copy()
    reps["geometry"] = reps.geometry.representative_point()
    rep_hits = gpd.sjoin(reps, gw, how="inner", predicate="within")[["field_id", "EU_CD_N"]].drop_duplicates()
    rep_pairs = set(map(tuple, rep_hits[["field_id", "EU_CD_N"]].itertuples(index=False, name=None)))
    positive["representative_point_inside"] = [
        (fid, euid) in rep_pairs for fid, euid in positive[["field_id", "EU_CD_N"]].itertuples(index=False, name=None)
    ]

    # Dominant body: maximum overlap area; EU_CD is deterministic tie-breaker.
    dominant = positive.sort_values(
        ["field_id", "overlap_m2", "EU_CD_N"], ascending=[True, False, True]
    ).drop_duplicates("field_id", keep="first").copy()
    dominant = dominant[["field_id", "EU_CD_N", "overlap_m2", "overlap_fraction", "representative_point_inside"]]
    dominant = dominant.rename(columns={"EU_CD_N": "dominant_EU_CD"})

    intersect_ids = set(cand["field_id"])
    area_ids = set(positive["field_id"])
    rep_ids = set(rep_hits["field_id"])
    touch_only_ids = intersect_ids - area_ids

    # Coverage at useful overlap thresholds; these are diagnostics, not frozen cutoffs.
    thresholds = [0.01, 0.10, 0.50, 0.90]
    threshold_counts = {
        str(t): int(positive.loc[positive["overlap_fraction"] >= t, "field_id"].nunique()) for t in thresholds
    }

    # Multiplicity matters because aquifers may be layered.
    multiplicity = positive.groupby("field_id")["EU_CD_N"].nunique()
    mult_counts = multiplicity.value_counts().sort_index().to_dict()

    name_map = {norm(w.get("EU_CD")): str(w.get("Name") or w.get("EU_CD")) for w in waters}
    per_water = positive.groupby("EU_CD_N").agg(
        fields_positive_area=("field_id", "nunique"),
        relations=("field_id", "size"),
        overlap_area_ha=("overlap_m2", lambda x: float(x.sum() / 10000.0)),
        median_overlap_fraction=("overlap_fraction", "median"),
    ).reset_index()
    per_water["name"] = per_water["EU_CD_N"].map(name_map)
    rep_count = rep_hits.groupby("EU_CD_N")["field_id"].nunique().rename("fields_rep_point").reset_index()
    per_water = per_water.merge(rep_count, on="EU_CD_N", how="left").fillna({"fields_rep_point": 0})
    per_water["fields_rep_point"] = per_water["fields_rep_point"].astype(int)
    per_water = per_water.sort_values(["fields_positive_area", "EU_CD_N"], ascending=[False, True])

    print("\nJOIN COMPARISON")
    print("-" * 88)
    print(f"VT-A2 intersects fields:                 {len(intersect_ids):,}")
    print(f"Positive-area overlap fields:            {len(area_ids):,}")
    print(f"Touch-only fields removed:               {len(touch_only_ids):,}")
    print(f"Representative-point-in-case fields:     {len(rep_ids):,}")
    for t in thresholds:
        print(f"Fields with >= {100*t:>4.0f}% overlap:              {threshold_counts[str(t)]:,}")

    print("\nLAYER MULTIPLICITY (positive-area relations per field)")
    print("-" * 88)
    for n, count in mult_counts.items():
        print(f"{int(n)} case GW body/bodies: {int(count):,} fields")

    print("\nPER-WATER-BODY ROBUST COVERAGE")
    print("-" * 88)
    print(per_water.to_string(index=False))

    # Save all non-zero overlap relations; this is the scientifically useful base.
    rel_cols = ["field_id", "EU_CD_N", "overlap_m2", "overlap_fraction", "representative_point_inside"]
    positive[rel_cols].sort_values(["field_id", "overlap_m2"], ascending=[True, False]).to_parquet(
        OUT / "field_case_overlap_relations.parquet", index=False
    )
    dominant.sort_values("field_id").to_parquet(OUT / "field_dominant_case.parquet", index=False)
    per_water.to_csv(OUT / "case_waterbody_robust_coverage.csv", index=False, encoding="utf-8-sig")

    summary = {
        "status": "PASS",
        "field_source": str(field_source),
        "positive_case_polygons": len(gw),
        "fields_intersects": len(intersect_ids),
        "fields_positive_area": len(area_ids),
        "fields_touch_only": len(touch_only_ids),
        "fields_representative_point_inside": len(rep_ids),
        "overlap_threshold_field_counts": threshold_counts,
        "positive_relation_multiplicity": {str(int(k)): int(v) for k, v in mult_counts.items()},
        "dominant_rule": "maximum overlap area; EU_CD lexical tie-break",
        "interpretation": "Retain all positive-area relations; dominant body is product convenience because GW bodies may be layered.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSaved: data/derived/akervatten/viss_vt_a2b/")
    print("VT-A2b ROBUST JOIN COMPLETE")
    print("=" * 88)


if __name__ == "__main__":
    main()
