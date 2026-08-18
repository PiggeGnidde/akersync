#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync · extreme Ferrari anomaly analysis · v0d.

Post-processes the v0c skifte Ferrari scores.  The goal is to replace the broad
P20 Ferrari-like diagnostic with deliberately extreme, easier-to-interpret
natural experiments:

* super-Ferrari outside historic class 10: FerrariScore >= class-10 OOF P90
* super-non-Ferrari inside class 10: FerrariScore <= class-10 OOF P05

For the outside-class-10 group the script also calculates true planar distance
from the skifte polygon to the nearest historic class-10 polygon and distance
from the skifte representative point to class 10.  This lets us distinguish
boundary artefacts from genuinely isolated soil analogues.

No climate, topography or hydrology is introduced here.  Those remain held out
as candidate explanations for the anomalies in a later stage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from common import load_config

V0C_DIRNAME = "agri_class5_10_v0c_ferrari"
OUT_DIRNAME = "agri_class5_10_v0d_extremes"
P_SUPER = 0.90
P_EXTREME_LOW = 0.05
P_ULTRA = 0.95
MIN_CLASS = 5
MAX_CLASS = 10


def load_class_polygons(root: Path, v0c_dir: Path) -> gpd.GeoDataFrame:
    candidates = [
        v0c_dir / "source" / "jord_skogsklassificering_class5_10.gpkg",
        root / "data" / "derived" / "agri_class5_10_v0b" / "source" / "jord_skogsklassificering_class5_10.gpkg",
    ]
    for p in candidates:
        if p.exists():
            print("Using historic class polygons:", p)
            return gpd.read_file(p, layer="class5_10").to_crs(3006)
    raise FileNotFoundError(
        "Klasspolygon-cache saknas. Kör RUN_AGRI_CLASS5_10_V0B.bat eller RUN_AGRI_FERRARI_V0C.bat först."
    )


def attach_geometry(scores: pd.DataFrame, skiften_path: Path) -> gpd.GeoDataFrame:
    skiften = gpd.read_file(skiften_path).to_crs(3006)
    if "arslager" in skiften.columns:
        skiften = skiften[pd.to_numeric(skiften["arslager"], errors="coerce").eq(2025)].copy()
    skiften = skiften[skiften.geometry.notna() & ~skiften.geometry.is_empty].reset_index(drop=True)

    d = scores.copy()
    d["row_index"] = pd.to_numeric(d["row_index"], errors="coerce")
    bad = d["row_index"].isna() | d["row_index"].lt(0) | d["row_index"].ge(len(skiften))
    if bad.any():
        raise RuntimeError(f"{int(bad.sum())} v0c rows have invalid row_index for current skifte file")
    d["row_index"] = d["row_index"].astype(int)
    geoms = skiften.geometry.iloc[d["row_index"].to_numpy()].reset_index(drop=True)
    g = gpd.GeoDataFrame(d.reset_index(drop=True), geometry=geoms, crs=3006)
    return g


def class10_thresholds(scored: pd.DataFrame) -> dict[str, float]:
    q = scored[
        scored["score_eligible"].astype(bool)
        & pd.to_numeric(scored["historic_class"], errors="coerce").eq(10)
        & pd.to_numeric(scored["ferrari_score"], errors="coerce").notna()
    ].copy()
    if len(q) < 100:
        raise RuntimeError(f"Too few eligible class-10 scored skiften: {len(q)}")
    s = pd.to_numeric(q["ferrari_score"], errors="coerce").dropna()
    return {
        "p05": float(s.quantile(0.05)),
        "p10": float(s.quantile(0.10)),
        "p20": float(s.quantile(0.20)),
        "p50": float(s.quantile(0.50)),
        "p75": float(s.quantile(0.75)),
        "p90": float(s.quantile(P_SUPER)),
        "p95": float(s.quantile(P_ULTRA)),
        "n": int(len(s)),
    }


def add_class10_distances(g: gpd.GeoDataFrame, class10_geom) -> gpd.GeoDataFrame:
    z = g.copy()
    if z.empty:
        z["distance_to_class10_edge_km"] = pd.Series(dtype=float)
        z["distance_rep_point_to_class10_km"] = pd.Series(dtype=float)
        z["distance_bin"] = pd.Series(dtype=str)
        return z
    z["distance_to_class10_edge_km"] = z.geometry.distance(class10_geom) / 1000.0
    rp = z.geometry.representative_point()
    z["distance_rep_point_to_class10_km"] = rp.distance(class10_geom) / 1000.0
    z["rep_lon"] = gpd.GeoSeries(rp, crs=3006).to_crs(4326).x.to_numpy()
    z["rep_lat"] = gpd.GeoSeries(rp, crs=3006).to_crs(4326).y.to_numpy()
    z["distance_bin"] = pd.cut(
        z["distance_to_class10_edge_km"],
        bins=[-np.inf, 2.0, 5.0, 10.0, np.inf],
        labels=["0-2 km", "2-5 km", "5-10 km", ">10 km"],
        right=False,
    ).astype(str)
    return z


def by_class_summary(scored: pd.DataFrame, p90: float, p95: float) -> pd.DataFrame:
    rows = []
    d = scored[scored["score_eligible"].astype(bool)].copy()
    d["historic_class"] = pd.to_numeric(d["historic_class"], errors="coerce")
    d["ferrari_score"] = pd.to_numeric(d["ferrari_score"], errors="coerce")
    for k in range(MIN_CLASS, MAX_CLASS + 1):
        q = d[d["historic_class"].eq(k)]
        n = len(q)
        n90 = int(q["ferrari_score"].ge(p90).sum())
        n95 = int(q["ferrari_score"].ge(p95).sum())
        rows.append({
            "historic_class": k,
            "n_eligible": n,
            "n_ge_class10_p90": n90,
            "share_ge_class10_p90_pct": 100.0 * n90 / n if n else np.nan,
            "n_ge_class10_p95": n95,
            "share_ge_class10_p95_pct": 100.0 * n95 / n if n else np.nan,
            "median_ferrari_score": float(q["ferrari_score"].median()) if n else np.nan,
        })
    return pd.DataFrame(rows)


def distance_summary(outside: pd.DataFrame) -> pd.DataFrame:
    if outside.empty:
        return pd.DataFrame(columns=["distance_bin", "n", "share_pct"])
    order = ["0-2 km", "2-5 km", "5-10 km", ">10 km"]
    c = outside["distance_bin"].value_counts().reindex(order, fill_value=0)
    return pd.DataFrame({
        "distance_bin": order,
        "n": [int(c[x]) for x in order],
        "share_pct": [100.0 * int(c[x]) / len(outside) for x in order],
    })


def escape_json_for_html(s: str) -> str:
    return s.replace("</", "<\\/")


def build_map(outside: gpd.GeoDataFrame, inside_bad: gpd.GeoDataFrame,
              classes: gpd.GeoDataFrame, outpath: Path, thresholds: dict):
    def prep(g):
        z = g.to_crs(3006).copy()
        if not z.empty:
            z["geometry"] = z.geometry.simplify(4.0, preserve_topology=True)
        z = z.to_crs(4326)
        keep = [
            "blockid", "skiftesbeteckning", "historic_class", "geom_area_ha",
            "class_overlap_share", "soil_coverage_pct", "clay_mean_pct",
            "silt_mean_pct", "sand_mean_pct", "clay_sd_pct", "silt_sd_pct",
            "sand_sd_pct", "texture_center_score", "homogeneity_score",
            "ferrari_score", "distance_to_class10_edge_km",
            "distance_rep_point_to_class10_km", "distance_bin", "geometry",
        ]
        return z[[c for c in keep if c in z.columns]]

    out_w = prep(outside)
    bad_w = prep(inside_bad)
    cls = classes[["KLASS", "geometry"]].to_crs(3006).copy()
    cls["geometry"] = cls.geometry.simplify(20.0, preserve_topology=True)
    cls = cls.to_crs(4326)
    bounds = cls.total_bounds.tolist()

    gj_out = escape_json_for_html(out_w.to_json(drop_id=True))
    gj_bad = escape_json_for_html(bad_w.to_json(drop_id=True))
    gj_cls = escape_json_for_html(cls.to_json(drop_id=True))

    html = f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ÅkerSync · extrema Ferrari-anomalier v0d</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><style>html,body,#map{{height:100%;margin:0}} .box{{background:white;padding:9px 11px;border-radius:7px;box-shadow:0 1px 6px #777;font:13px Arial;max-width:420px}} .legend i{{display:inline-block;width:13px;height:13px;margin-right:6px;vertical-align:-2px}}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const classes={gj_cls}; const outside={gj_out}; const bad={gj_bad}; const map=L.map('map');
const osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OpenStreetMap'}}).addTo(map);
const esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:'Esri'}});
const classColors={{5:'#ffffbf',6:'#fee090',7:'#fdae61',8:'#f46d43',9:'#d73027',10:'#7f0000'}};
const distanceColors={{'0-2 km':'#ffd92f','2-5 km':'#ff7f00','5-10 km':'#e31a1c','>10 km':'#6a3d9a'}};
const clsLayer=L.geoJSON(classes,{{style:f=>({{color:classColors[f.properties.KLASS]||'#777',weight:f.properties.KLASS===10?3.0:0.8,fillColor:classColors[f.properties.KLASS]||'#777',fillOpacity:f.properties.KLASS===10?0.08:0.01}}),onEachFeature:(f,l)=>l.bindTooltip('Historisk klass '+f.properties.KLASS)}}).addTo(map);
function popup(p){{let dist=(p.distance_to_class10_edge_km==null?'—':Number(p.distance_to_class10_edge_km).toFixed(1)+' km');return `<b>Skifte ${{p.skiftesbeteckning||''}}</b><br>Block ${{p.blockid||''}}<br>Historisk klass: <b>${{p.historic_class}}</b><br>FerrariScore: <b>${{Number(p.ferrari_score).toFixed(1)}}</b><br>Avstånd till klass 10: <b>${{dist}}</b><br>Center: ${{Number(p.texture_center_score).toFixed(1)}} · homogenitet: ${{Number(p.homogeneity_score).toFixed(1)}}<br>Lera/silt/sand: ${{Number(p.clay_mean_pct).toFixed(1)}} / ${{Number(p.silt_mean_pct).toFixed(1)}} / ${{Number(p.sand_mean_pct).toFixed(1)}} %<br>SD: ${{Number(p.clay_sd_pct).toFixed(1)}} / ${{Number(p.silt_sd_pct).toFixed(1)}} / ${{Number(p.sand_sd_pct).toFixed(1)}}<br>Klassöverlapp: ${{(100*Number(p.class_overlap_share)).toFixed(0)}}% · jordtäckning: ${{Number(p.soil_coverage_pct).toFixed(0)}}%`;}}
const outLayer=L.geoJSON(outside,{{style:f=>{{let c=distanceColors[f.properties.distance_bin]||'#333';return {{color:c,weight:2.3,fillColor:c,fillOpacity:.62}};}},onEachFeature:(f,l)=>l.bindPopup(popup(f.properties))}}).addTo(map);
const badLayer=L.geoJSON(bad,{{style:{{color:'#00a6d6',weight:2.3,fillColor:'#00c5e5',fillOpacity:.55}},onEachFeature:(f,l)=>l.bindPopup(popup(f.properties))}}).addTo(map);
L.control.layers({{'OpenStreetMap':osm,'Esri satellite':esri}},{{'Historiska klass 5–10':clsLayer,'Super-Ferrari utanför klass 10':outLayer,'Extrem icke-Ferrari i klass 10':badLayer}},{{collapsed:false}}).addTo(map);
map.fitBounds([[{bounds[1]},{bounds[0]}],[{bounds[3]},{bounds[2]}]]);
const info=L.control({{position:'topleft'}}); info.onAdd=()=>{{let d=L.DomUtil.create('div','box legend');d.innerHTML=`<b>ÅkerSync · extrema Ferrari-anomalier v0d</b><br>SOIL ONLY. Klimat/topografi/hydrologi hålls utanför.<br><br>Super-Ferrari = klass-10 OOF P90: <b>{thresholds['p90']:.1f}</b><br>Extrem icke-Ferrari = klass-10 OOF P05: <b>{thresholds['p05']:.1f}</b><br><br><i style="background:#ffd92f"></i>0–2 km från klass 10<br><i style="background:#ff7f00"></i>2–5 km<br><i style="background:#e31a1c"></i>5–10 km<br><i style="background:#6a3d9a"></i>&gt;10 km<br><i style="background:#00c5e5"></i>Extrem låg score inne i klass 10`;return d;}}; info.addTo(map);
</script></body></html>'''
    outpath.write_text(html, encoding="utf-8")


def write_report(outpath: Path, thresholds: dict, byclass: pd.DataFrame,
                 dsum: pd.DataFrame, outside: pd.DataFrame, inside_bad: pd.DataFrame):
    lines = [
        "ÅkerSync · extreme Ferrari anomaly analysis · v0d",
        "=" * 78,
        "Post-processing of v0c soil-only, spatial-holdout Ferrari scores.",
        "Climate/topography/hydrology are intentionally still held out.",
        "",
        f"Eligible class-10 OOF reference n: {thresholds['n']:,}",
        f"Class-10 score P05: {thresholds['p05']:.2f}",
        f"Class-10 score P50: {thresholds['p50']:.2f}",
        f"Class-10 score P90: {thresholds['p90']:.2f}",
        f"Class-10 score P95: {thresholds['p95']:.2f}",
        "",
        f"SUPER-FERRARI outside class 10 (>= P90): {len(outside):,}",
        f"EXTREME non-Ferrari inside class 10 (<= P05): {len(inside_bad):,}",
        "",
        "SUPER-FERRARI BY HISTORIC CLASS",
    ]
    for _, r in byclass.iterrows():
        lines.append(
            f"  Class {int(r.historic_class)}: eligible {int(r.n_eligible):,}; "
            f">=P90 {int(r.n_ge_class10_p90):,} ({r.share_ge_class10_p90_pct:.2f}%); "
            f">=P95 {int(r.n_ge_class10_p95):,} ({r.share_ge_class10_p95_pct:.2f}%)"
        )
    lines += ["", "DISTANCE FROM SUPER-FERRARI OUTSIDE CLASS 10 TO NEAREST CLASS-10 POLYGON"]
    for _, r in dsum.iterrows():
        lines.append(f"  {r.distance_bin}: {int(r.n):,} ({r.share_pct:.1f}%)")
    if len(outside):
        lines += [
            "",
            f"Maximum edge distance: {outside.distance_to_class10_edge_km.max():.1f} km",
            f"Median edge distance: {outside.distance_to_class10_edge_km.median():.1f} km",
            f"Super-Ferrari >10 km from class 10: {int(outside.distance_to_class10_edge_km.ge(10).sum()):,}",
        ]
    lines += [
        "",
        "Interpretation guardrails:",
        "- P90/P05 are deliberately extreme diagnostics, not agronomic universal cut-offs.",
        "- Outside-class-10 means historic production class <10; it does not mean class-10 production potential.",
        "- Distance helps distinguish old map-boundary artefacts from geographically isolated soil analogues.",
        "- DSMS2025 is modeled soil information. Anomaly follow-up should use held-out climate/topography/hydrology and, where possible, independent field/soil data.",
    ]
    outpath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    build_dir = root / cfg.get("build_dir", "data/derived")
    v0c_dir = build_dir / V0C_DIRNAME
    outdir = build_dir / OUT_DIRNAME
    outdir.mkdir(parents=True, exist_ok=True)

    scores_path = v0c_dir / "skifte_ferrari_scores.csv"
    if not scores_path.exists():
        raise FileNotFoundError(
            f"v0c score file missing: {scores_path}\nRun RUN_AGRI_FERRARI_V0C.bat first."
        )
    skiften_path = Path(cfg.get("skiften", ""))
    if not skiften_path.exists():
        raise FileNotFoundError(f"Skiftefil saknas: {skiften_path}")

    print("=" * 92)
    print("ÅkerSync · extreme Ferrari anomaly analysis · v0d")
    print("=" * 92)
    print("Input v0c:", scores_path)
    print("Output:", outdir)
    print()

    scores = pd.read_csv(scores_path, encoding="utf-8-sig")
    # CSV can materialize bools either as bool or strings depending on pandas/version.
    if scores["score_eligible"].dtype != bool:
        scores["score_eligible"] = scores["score_eligible"].astype(str).str.casefold().isin(["true", "1", "yes"])
    scores["historic_class"] = pd.to_numeric(scores["historic_class"], errors="coerce")
    scores["ferrari_score"] = pd.to_numeric(scores["ferrari_score"], errors="coerce")

    thresholds = class10_thresholds(scores)
    print("Class-10 score thresholds:", json.dumps(thresholds, ensure_ascii=False, indent=2))

    classes = load_class_polygons(root, v0c_dir)
    class10 = classes[pd.to_numeric(classes["KLASS"], errors="coerce").eq(10)].copy()
    if class10.empty:
        raise RuntimeError("No class-10 polygon found")
    class10_geom = class10.geometry.union_all() if hasattr(class10.geometry, "union_all") else class10.geometry.unary_union

    scored_g = attach_geometry(scores, skiften_path)
    eligible = scored_g[scored_g["score_eligible"]].copy()

    outside = eligible[
        eligible["historic_class"].lt(10)
        & eligible["ferrari_score"].ge(thresholds["p90"])
    ].copy()
    outside = add_class10_distances(outside, class10_geom)
    outside["ultra_ferrari_ge_p95"] = outside["ferrari_score"].ge(thresholds["p95"])
    outside = outside.sort_values(["distance_to_class10_edge_km", "ferrari_score"], ascending=[False, False])

    inside_bad = eligible[
        eligible["historic_class"].eq(10)
        & eligible["ferrari_score"].le(thresholds["p05"])
    ].copy().sort_values("ferrari_score", ascending=True)

    byclass = by_class_summary(scores, thresholds["p90"], thresholds["p95"])
    dsum = distance_summary(outside)

    # Add convenient WGS84 representative-point coordinates to both anomaly tables.
    for g in (outside, inside_bad):
        if len(g) and "rep_lon" not in g.columns:
            rp = g.geometry.representative_point()
            rp_ll = gpd.GeoSeries(rp, crs=3006).to_crs(4326)
            g["rep_lon"] = rp_ll.x.to_numpy()
            g["rep_lat"] = rp_ll.y.to_numpy()

    csv_drop = ["geometry"]
    outside.drop(columns=csv_drop, errors="ignore").to_csv(outdir / "super_ferrari_outside_class10.csv", index=False, encoding="utf-8-sig")
    inside_bad.drop(columns=csv_drop, errors="ignore").to_csv(outdir / "extreme_non_ferrari_inside_class10.csv", index=False, encoding="utf-8-sig")
    byclass.to_csv(outdir / "super_ferrari_by_historic_class.csv", index=False, encoding="utf-8-sig")
    dsum.to_csv(outdir / "super_ferrari_distance_bins.csv", index=False, encoding="utf-8-sig")

    gpkg = outdir / "ferrari_extreme_anomalies.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    if len(outside):
        outside.to_file(gpkg, layer="super_ferrari_outside_class10", driver="GPKG")
    if len(inside_bad):
        inside_bad.to_file(gpkg, layer="extreme_non_ferrari_inside_class10", driver="GPKG")
    class10.to_file(gpkg, layer="historic_class10", driver="GPKG")

    build_map(outside, inside_bad, classes, outdir / "ferrari_extreme_anomaly_map.html", thresholds)
    write_report(outdir / "report.txt", thresholds, byclass, dsum, outside, inside_bad)

    metadata = {
        "input_scores": str(scores_path),
        "p_super": P_SUPER,
        "p_extreme_low": P_EXTREME_LOW,
        "p_ultra": P_ULTRA,
        "thresholds": thresholds,
        "distance_definition": "minimum planar EPSG:3006 polygon-edge distance to union of historic class-10 polygons",
        "held_out_predictors": ["climate", "topography", "hydrology"],
    }
    (outdir / "method_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print((outdir / "report.txt").read_text(encoding="utf-8"))
    print("Map:", outdir / "ferrari_extreme_anomaly_map.html")
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
