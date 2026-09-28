"""ÅkerKontext · VattenTryck — VT-A2 VISS groundwater spatial coverage.

Downloads current VISS groundwater polygons from Länsstyrelsen ArcGIS REST,
joins the VT-A1 positive pressure/risk cases by EU_CD, and spatially intersects
those polygons with the local 2025 Skåne field layer from config/local_paths.json.

Inventory only: no score, no legal inference, no modification of ÅkerVatten web.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "local_paths.json"
A1C = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1c"
A1E = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1e"
OUT = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a2"
EXPECTED_FIELDS = 128_636
KEY = ["blockid", "skiftesbeteckning"]

# Länsstyrelsen VISS2, groundwater layer (polygon). ArcGIS REST query endpoint.
QUERY_URL = (
    "https://ext-geodata-acc.lansstyrelsen.se/arcgis/rest/services/"
    "VISS2/lst_viss2_vattenforekomster/MapServer/1/query"
)


def read_json(path: Path):
    if not path.exists():
        raise RuntimeError(f"Missing {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm(x):
    return "" if x is None else str(x).strip().upper()


def download_viss_geojson(path: Path) -> None:
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "3006",
        "f": "geojson",
    }
    url = QUERY_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync-VISS-VT-A2/0a"})
    with urllib.request.urlopen(req, timeout=240) as r:
        raw = r.read()
    # ArcGIS may return JSON error despite requested GeoJSON.
    text = raw.decode("utf-8-sig")
    doc = json.loads(text)
    if isinstance(doc, dict) and doc.get("error"):
        raise RuntimeError(f"ArcGIS error: {doc['error']}")
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise RuntimeError("VISS geometry endpoint did not return a GeoJSON FeatureCollection")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"Downloaded VISS GW geometry: {len(doc.get('features', [])):,} features, {len(raw):,} bytes")


def find_col(cols, names):
    lookup = {str(c).upper(): c for c in cols}
    for name in names:
        if name.upper() in lookup:
            return lookup[name.upper()]
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 82)
    print("ÅkerKontext · VattenTryck — VT-A2 VISS spatial coverage")
    print("=" * 82)

    cfg = read_json(CONFIG)
    skifte_path = Path(cfg["skiften"])
    if not skifte_path.exists():
        raise RuntimeError(f"Configured skiften file missing: {skifte_path}")

    waters = read_json(A1C / "waters.json")
    cases = read_json(A1E / "summary.json")
    pressure_rows = read_json(A1C / "measuregroundwaterpressuremotivations.json")
    risks = read_json(A1C / "waterriskclassifications.json")
    gw_ids = {norm(w.get("EU_CD")) for w in waters}
    case_ids = {norm(x) for x in cases["case_ids"]}

    geo_path = OUT / "viss_groundwater_all.geojson"
    download_viss_geojson(geo_path)
    gw = gpd.read_file(geo_path)
    if gw.crs is None:
        gw = gw.set_crs(3006)
    else:
        gw = gw.to_crs(3006)
    eucol = find_col(gw.columns, ["EU_CD", "VISS_EU_CD"])
    if eucol is None:
        raise RuntimeError(f"No EU_CD/VISS_EU_CD in VISS geometry. Columns: {list(gw.columns)}")
    gw["EU_CD_N"] = gw[eucol].map(norm)
    matched_api = gw["EU_CD_N"].isin(gw_ids)
    matched_cases = gw["EU_CD_N"].isin(case_ids)
    print(f"VISS polygon features:                 {len(gw):,}")
    print(f"Polygons matching 181 API GW IDs:      {int(matched_api.sum()):,} / {len(gw_ids):,}")
    print(f"Positive-case polygons matched:        {int(matched_cases.sum()):,} / {len(case_ids):,}")

    fields = gpd.read_file(skifte_path)
    if fields.crs is None:
        raise RuntimeError("Skiften layer has no CRS")
    fields = fields.to_crs(3006)
    if len(fields) != EXPECTED_FIELDS:
        raise RuntimeError(f"Expected {EXPECTED_FIELDS:,} Skåne fields, got {len(fields):,}")
    missing = [c for c in KEY if c not in fields.columns]
    if missing:
        raise RuntimeError(f"Skiften missing key columns: {missing}")
    fields[KEY] = fields[KEY].astype(str)
    fields["field_id"] = fields["blockid"] + "|" + fields["skiftesbeteckning"]
    if fields["field_id"].duplicated().any():
        raise RuntimeError("Duplicate field IDs in skiften layer")
    print(f"Skåne fields loaded:                   {len(fields):,}")

    # Intersect only polygons represented by the API inventory. A field can overlap
    # multiple layered groundwater bodies; retain all relations and count unique fields.
    api_poly = gw.loc[matched_api, ["EU_CD_N", "geometry"]].copy()
    api_poly = api_poly[~api_poly.geometry.is_empty & api_poly.geometry.notna()]
    hit_all = gpd.sjoin(fields[["field_id", "geometry"]], api_poly, how="inner", predicate="intersects")
    all_field_ids = set(hit_all["field_id"])

    case_poly = gw.loc[matched_cases, ["EU_CD_N", "geometry"]].copy()
    hit_case = gpd.sjoin(fields[["field_id", "geometry"]], case_poly, how="inner", predicate="intersects")
    case_field_ids = set(hit_case["field_id"])

    # Build positive withdrawal categories per water body from exact VISS Y rows.
    cat_by_water = {}
    for r in pressure_rows:
        euid = norm(r.get("WaterEUID"))
        ptype = str(r.get("MeasureGroundWaterPressureType") or "")
        if euid not in gw_ids or "uttag" not in ptype.lower() or str(r.get("Classification") or "").strip() != "Y":
            continue
        cats = cat_by_water.setdefault(euid, set())
        low = ptype.lower()
        if "jordbruk" in low: cats.add("agriculture")
        elif "kommunal" in low or "allmän" in low: cats.add("municipal")
        elif "tillverkningsindustri" in low: cats.add("industry")
        elif ptype.strip() == "3 Vattenuttag": cats.add("generic")
        else: cats.add("other")

    quantitative_ids = set()
    for r in risks:
        euid = norm(r.get("EU_CD"))
        if euid not in gw_ids or str(r.get("WaterCategory") or "") != "GW":
            continue
        for sec in r.get("RiskSections") or []:
            if sec.get("SectionName") == "Kvantitativ status - Grundvatten" and sec.get("Risk") not in (None, "", "Ej klassad", "Ingen"):
                quantitative_ids.add(euid)

    field_sets = {}
    for cat in ["agriculture", "municipal", "industry", "generic", "other"]:
        ids = {e for e, cats in cat_by_water.items() if cat in cats}
        field_sets[cat] = set(hit_case.loc[hit_case["EU_CD_N"].isin(ids), "field_id"])
    field_sets["quantitative_risk"] = set(hit_case.loc[hit_case["EU_CD_N"].isin(quantitative_ids), "field_id"])

    print("\nFIELD COVERAGE")
    print("-" * 82)
    print(f"Any VISS GW polygon:                   {len(all_field_ids):,} ({100*len(all_field_ids)/len(fields):.2f}%)")
    print(f"Any positive withdrawal/risk case:     {len(case_field_ids):,} ({100*len(case_field_ids)/len(fields):.2f}%)")
    for cat in ["agriculture", "municipal", "industry", "generic", "other", "quantitative_risk"]:
        print(f"{cat:38s}{len(field_sets[cat]):>8,} ({100*len(field_sets[cat])/len(fields):.2f}%)")

    # Per-water-body unique field counts.
    per_water = (hit_case.groupby("EU_CD_N")["field_id"].nunique().rename("fields_intersecting").reset_index())
    name_map = {norm(w.get("EU_CD")): str(w.get("Name") or w.get("EU_CD")) for w in waters}
    per_water["name"] = per_water["EU_CD_N"].map(name_map)
    per_water["pressure_categories"] = per_water["EU_CD_N"].map(lambda x: ";".join(sorted(cat_by_water.get(x, set()))))
    per_water["quantitative_risk"] = per_water["EU_CD_N"].isin(quantitative_ids)
    per_water = per_water.sort_values(["fields_intersecting", "EU_CD_N"], ascending=[False, True])
    per_water.to_csv(OUT / "case_waterbody_field_coverage.csv", index=False, encoding="utf-8-sig")

    # Field relations for later product/web work; many-to-many is intentional.
    rel = hit_case[["field_id", "EU_CD_N"]].drop_duplicates().sort_values(["field_id", "EU_CD_N"])
    rel.to_parquet(OUT / "field_case_relations.parquet", index=False)

    summary = {
        "status": "PASS",
        "fields": len(fields),
        "viss_api_gw_water_bodies": len(gw_ids),
        "viss_polygon_features": len(gw),
        "api_ids_with_polygon": int(matched_api.sum()),
        "positive_case_water_bodies": len(case_ids),
        "positive_case_ids_with_polygon": int(matched_cases.sum()),
        "fields_any_viss_gw": len(all_field_ids),
        "fields_any_positive_case": len(case_field_ids),
        "field_coverage": {k: len(v) for k, v in field_sets.items()},
        "note": "Spatial predicate is intersects; layered GW bodies may create multiple relations per field.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nTOP CASE WATER BODIES BY FIELD COUNT")
    print("-" * 82)
    print(per_water.head(20).to_string(index=False))
    print("\nSaved: data/derived/akervatten/viss_vt_a2/")
    print("VT-A2 SPATIAL COVERAGE COMPLETE")
    print("=" * 82)


if __name__ == "__main__":
    main()
