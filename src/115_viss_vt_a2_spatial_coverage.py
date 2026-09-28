"""ÅkerKontext · VattenTryck — VT-A2 VISS groundwater spatial coverage.

Downloads current VISS groundwater polygons from Länsstyrelsen ArcGIS REST,
joins VT-A1 positive pressure/risk cases by EU_CD, and spatially intersects
those polygons with the existing local 2025 Skåne field geometry.

The field source is resolved without requiring a new local config: first an
optional AKERSYNC_SKIFTEN_PATH environment variable, then legacy local_paths if
present, then deterministic discovery in the existing ÅkerSync/ÅkerVatten
working trees. Inventory only: no score, no legal inference, no web changes.
"""
from __future__ import annotations

import json
import os
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
VECTOR_EXT = {".gpkg", ".geojson", ".json", ".shp", ".parquet"}

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
    params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "3006", "f": "geojson"}
    url = QUERY_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync-VISS-VT-A2/0a"})
    with urllib.request.urlopen(req, timeout=240) as r:
        raw = r.read()
    doc = json.loads(raw.decode("utf-8-sig"))
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


def read_vector(path: Path) -> gpd.GeoDataFrame:
    if path.suffix.lower() == ".parquet":
        return gpd.read_parquet(path)
    return gpd.read_file(path)


def candidate_roots() -> list[Path]:
    roots = [ROOT]
    parent = ROOT.parent
    # Existing project convention uses sibling checkouts such as AkerSync-AkerVatten*.
    for p in sorted(parent.glob("AkerSync*")):
        if p.is_dir() and p not in roots:
            roots.append(p)
    return roots


def resolve_skiften() -> tuple[Path, gpd.GeoDataFrame]:
    explicit = os.environ.get("AKERSYNC_SKIFTEN_PATH", "").strip()
    if explicit:
        p = Path(explicit)
        q = read_vector(p)
        print(f"Field source: AKERSYNC_SKIFTEN_PATH -> {p}")
        return p, q

    if CONFIG.exists():
        cfg = read_json(CONFIG)
        value = cfg.get("skiften")
        if value and Path(value).exists():
            p = Path(value)
            q = read_vector(p)
            print(f"Field source: legacy local_paths.json -> {p}")
            return p, q

    # Discover only plausibly named vector files; skip caches/build output and VISS itself.
    candidates: list[Path] = []
    seen = set()
    for base in candidate_roots():
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in VECTOR_EXT:
                continue
            low = str(p).lower()
            name = p.name.lower()
            if not any(token in name for token in ("skift", "field", "jordbruk")):
                continue
            if any(token in low for token in ("viss_vt_a", "dist\\", "dist/", "node_modules", ".git")):
                continue
            key = str(p.resolve()).lower()
            if key not in seen:
                seen.add(key)
                candidates.append(p)

    print(f"Field-source autodiscovery: {len(candidates)} plausible vector files")
    valid = []
    for p in candidates:
        try:
            q = read_vector(p)
        except Exception:
            continue
        if all(c in q.columns for c in KEY) and "geometry" in q.columns and q.crs is not None:
            print(f"  candidate: {p} -> {len(q):,} rows")
            if len(q) == EXPECTED_FIELDS:
                valid.append((p, q))

    if len(valid) == 1:
        print(f"Field source selected: {valid[0][0]}")
        return valid[0]
    if len(valid) > 1:
        # Same dataset can exist in several experiment trees. Prefer current/sibling
        # ÅkerVatten tree deterministically; identical row count/keys are verified below.
        valid.sort(key=lambda x: (0 if "akervatten" in str(x[0]).lower() else 1, len(str(x[0])), str(x[0])))
        print(f"Multiple complete sources found; selected deterministically: {valid[0][0]}")
        return valid[0]

    raise RuntimeError(
        "Could not auto-discover one complete 128,636-row Skåne field geometry with "
        "blockid + skiftesbeteckning. No files were changed."
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 82)
    print("ÅkerKontext · VattenTryck — VT-A2 VISS spatial coverage")
    print("=" * 82)

    waters = read_json(A1C / "waters.json")
    cases = read_json(A1E / "summary.json")
    pressure_rows = read_json(A1C / "measuregroundwaterpressuremotivations.json")
    risks = read_json(A1C / "waterriskclassifications.json")
    gw_ids = {norm(w.get("EU_CD")) for w in waters}
    case_ids = {norm(x) for x in cases["case_ids"]}

    geo_path = OUT / "viss_groundwater_all.geojson"
    download_viss_geojson(geo_path)
    gw = gpd.read_file(geo_path)
    gw = gw.set_crs(3006) if gw.crs is None else gw.to_crs(3006)
    eucol = find_col(gw.columns, ["EU_CD", "VISS_EU_CD"])
    if eucol is None:
        raise RuntimeError(f"No EU_CD/VISS_EU_CD in VISS geometry. Columns: {list(gw.columns)}")
    gw["EU_CD_N"] = gw[eucol].map(norm)
    matched_api = gw["EU_CD_N"].isin(gw_ids)
    matched_cases = gw["EU_CD_N"].isin(case_ids)
    print(f"VISS polygon features:                 {len(gw):,}")
    print(f"Polygons matching 181 API GW IDs:      {int(matched_api.sum()):,} / {len(gw_ids):,}")
    print(f"Positive-case polygons matched:        {int(matched_cases.sum()):,} / {len(case_ids):,}")

    skifte_path, fields = resolve_skiften()
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

    api_poly = gw.loc[matched_api, ["EU_CD_N", "geometry"]].copy()
    api_poly = api_poly[~api_poly.geometry.is_empty & api_poly.geometry.notna()]
    hit_all = gpd.sjoin(fields[["field_id", "geometry"]], api_poly, how="inner", predicate="intersects")
    all_field_ids = set(hit_all["field_id"])

    case_poly = gw.loc[matched_cases, ["EU_CD_N", "geometry"]].copy()
    hit_case = gpd.sjoin(fields[["field_id", "geometry"]], case_poly, how="inner", predicate="intersects")
    case_field_ids = set(hit_case["field_id"])

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

    per_water = hit_case.groupby("EU_CD_N")["field_id"].nunique().rename("fields_intersecting").reset_index()
    name_map = {norm(w.get("EU_CD")): str(w.get("Name") or w.get("EU_CD")) for w in waters}
    per_water["name"] = per_water["EU_CD_N"].map(name_map)
    per_water["pressure_categories"] = per_water["EU_CD_N"].map(lambda x: ";".join(sorted(cat_by_water.get(x, set()))))
    per_water["quantitative_risk"] = per_water["EU_CD_N"].isin(quantitative_ids)
    per_water = per_water.sort_values(["fields_intersecting", "EU_CD_N"], ascending=[False, True])
    per_water.to_csv(OUT / "case_waterbody_field_coverage.csv", index=False, encoding="utf-8-sig")

    rel = hit_case[["field_id", "EU_CD_N"]].drop_duplicates().sort_values(["field_id", "EU_CD_N"])
    rel.to_parquet(OUT / "field_case_relations.parquet", index=False)

    summary = {
        "status": "PASS",
        "field_source": str(skifte_path),
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
