#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync · skifte-level Ferrari soil experiment · v0c.

Question:
    Do class-10-like fields exist outside historic class 10, and do
    non-class-10-like fields exist inside class 10?

This deliberately uses SOIL ONLY. Climate/topography/hydrology are kept out so
that any later explanation of anomalies is genuinely out-of-sample relative to
this soil signature.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape

from common import load_config

LAYER_URL = "https://kartportal.ystad.se/arcgis/rest/services/SAM/SAM_OP_Hansyn/MapServer/32"
QUERY_URL = LAYER_URL + "/query"
SOIL_MEMBERS = {
    "clay": "dsms2025_ler.tif",
    "sand": "dsms2025_sand.tif",
    "silt": "dsms2025_silt.tif",
}
CLASS_MIN = 5
CLASS_MAX = 10
MIN_SOIL_COVERAGE_PCT = 80.0
MIN_CLASS_OVERLAP_SHARE = 0.80
MIN_SKIFTE_HA = 1.0
GRID_M = 10_000.0
MIN_TRAIN_N = 30
CLASS10_KEEP_QUANTILE = 0.20
REGULARIZATION = 0.20


def arcgis_get(params, timeout=120):
    url = QUERY_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download_class_polygons(class_min=CLASS_MIN, class_max=CLASS_MAX):
    features = []
    offset = 0
    page_size = 1000
    where = f"KLASS >= {class_min} AND KLASS <= {class_max}"
    while True:
        data = arcgis_get({
            "where": where,
            "outFields": "OBJECTID_12,KLASS",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": "OBJECTID_12",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        })
        if "error" in data:
            raise RuntimeError("ArcGIS query failed: " + json.dumps(data["error"], ensure_ascii=False))
        batch = data.get("features", [])
        features.extend(batch)
        print(f"\rDownloaded class polygons: {len(features)}", end="", flush=True)
        if len(batch) < page_size:
            break
        offset += len(batch)
    print()
    if not features:
        raise RuntimeError("No agricultural class polygons returned.")
    rows, geoms = [], []
    for f in features:
        p = f.get("properties", {})
        rows.append({"OBJECTID_12": p.get("OBJECTID_12"), "KLASS": p.get("KLASS")})
        geoms.append(shape(f.get("geometry")))
    g = gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)
    g["KLASS"] = pd.to_numeric(g["KLASS"], errors="coerce").astype("Int64")
    g = g[g["KLASS"].between(class_min, class_max) & g.geometry.notna() & ~g.geometry.is_empty].copy()
    return g.to_crs(3006)


def load_classes(root: Path, outdir: Path, refresh: bool):
    v0b_cache = root / "data" / "derived" / "agri_class5_10_v0b" / "source" / "jord_skogsklassificering_class5_10.gpkg"
    own_cache = outdir / "source" / "jord_skogsklassificering_class5_10.gpkg"
    if not refresh:
        for p in (v0b_cache, own_cache):
            if p.exists():
                print("Using cached class polygons:", p)
                return gpd.read_file(p, layer="class5_10").to_crs(3006)
    print("Downloading historic class 5–10 polygons...")
    g = download_class_polygons()
    own_cache.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(own_cache, layer="class5_10", driver="GPKG")
    print("Cached:", own_cache)
    return g


def extract_member(zf, basename, td):
    member = next((n for n in zf.namelist() if n == basename or n.endswith("/" + basename)), None)
    if not member:
        raise RuntimeError("Soil ZIP saknar " + basename)
    zf.extract(member, td)
    return Path(td) / member


def crs_is_3006(crs):
    if crs is None:
        return False
    try:
        if crs.to_epsg() == 3006:
            return True
    except Exception:
        pass
    t = str(crs)
    return ('AUTHORITY["EPSG","3006"]' in t) or ("SWEREF99 TM" in t)


def geom_window(ds, geom):
    if geom is None or geom.is_empty:
        return None
    w = from_bounds(*geom.bounds, transform=ds.transform)
    c0 = max(0, int(math.floor(w.col_off)))
    r0 = max(0, int(math.floor(w.row_off)))
    c1 = min(ds.width, int(math.ceil(w.col_off + w.width)))
    r1 = min(ds.height, int(math.ceil(w.row_off + w.height)))
    if c1 <= c0 or r1 <= r0:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def valid_mask(arr, nodata):
    ok = np.isfinite(arr)
    if nodata is not None:
        ok &= arr != nodata
    return ok


def assign_historic_class(skiften: gpd.GeoDataFrame, classes: gpd.GeoDataFrame):
    dissolved = classes[["KLASS", "geometry"]].dissolve(by="KLASS").reset_index()
    dissolved["KLASS"] = dissolved["KLASS"].astype(int)
    pts = skiften[["geometry"]].copy()
    pts["geometry"] = pts.representative_point()
    joined = gpd.sjoin(pts, dissolved[["KLASS", "geometry"]], how="left", predicate="within")
    if joined.index.duplicated().any():
        joined = joined[~joined.index.duplicated(keep="first")]
    out = skiften.copy()
    out["historic_class"] = pd.to_numeric(joined["KLASS"].reindex(out.index), errors="coerce")
    out = out[out["historic_class"].between(CLASS_MIN, CLASS_MAX)].copy()
    out["historic_class"] = out["historic_class"].astype(int)
    out["geom_area_ha"] = out.geometry.area / 10000.0
    out["class_overlap_share"] = np.nan
    class_geom = {int(r.KLASS): r.geometry for _, r in dissolved.iterrows()}
    for k in range(CLASS_MIN, CLASS_MAX + 1):
        mask = out["historic_class"].eq(k)
        if not mask.any():
            continue
        inter_area = out.loc[mask, "geometry"].intersection(class_geom[k]).area
        denom = out.loc[mask, "geometry"].area.replace(0, np.nan)
        out.loc[mask, "class_overlap_share"] = np.clip((inter_area / denom).to_numpy(float), 0, 1)
    rp = out.representative_point()
    out["x_3006"] = rp.x
    out["y_3006"] = rp.y
    out["grid_x10km"] = np.floor(out["x_3006"] / GRID_M).astype(int)
    out["grid_y10km"] = np.floor(out["y_3006"] / GRID_M).astype(int)
    out["spatial_cell"] = out["grid_x10km"].astype(str) + "_" + out["grid_y10km"].astype(str)
    return out, dissolved


def sample_skiften_soil(skiften, soil_zip, outdir):
    print(f"Sampling soil for {len(skiften):,} class 5–10 skiften...")
    rows = []
    with tempfile.TemporaryDirectory(prefix="akersync_ferrari_") as td, zipfile.ZipFile(soil_zip) as zf:
        paths = {kind: extract_member(zf, base, td) for kind, base in SOIL_MEMBERS.items()}
        with rasterio.open(paths["clay"]) as clay, rasterio.open(paths["silt"]) as silt, rasterio.open(paths["sand"]) as sand:
            dsmap = {"clay": clay, "silt": silt, "sand": sand}
            ref = clay
            for kind, ds in dsmap.items():
                if not crs_is_3006(ds.crs):
                    raise RuntimeError(f"{paths[kind].name}: expected EPSG:3006/SWEREF99 TM, got {ds.crs}")
                if tuple(round(x, 6) for x in ds.res) != (20.0, 20.0):
                    raise RuntimeError(f"{paths[kind].name}: expected 20 m pixels, got {ds.res}")
                if ds.width != ref.width or ds.height != ref.height or ds.transform != ref.transform:
                    raise RuntimeError(f"{paths[kind].name}: raster grids do not align")
            for n, (idx, r) in enumerate(skiften.iterrows(), 1):
                geom = r.geometry
                w = geom_window(ref, geom)
                base = {
                    "row_index": int(idx),
                    "blockid": str(r.get("blockid", "")),
                    "skiftesbeteckning": str(r.get("skiftesbeteckning", "")),
                    "historic_class": int(r.historic_class),
                    "geom_area_ha": float(r.geom_area_ha),
                    "class_overlap_share": float(r.class_overlap_share) if pd.notna(r.class_overlap_share) else np.nan,
                    "spatial_cell": str(r.spatial_cell),
                    "x_3006": float(r.x_3006),
                    "y_3006": float(r.y_3006),
                }
                for c in ("ansokt_areal_ha", "faststalld_areal_ha", "grdkod_mar"):
                    if c in r.index:
                        base[c] = r.get(c)
                if w is None:
                    base["soil_coverage_pct"] = 0.0
                    rows.append(base)
                    continue
                tr = ref.window_transform(w)
                shape2 = (int(w.height), int(w.width))
                pmask = geometry_mask([geom.__geo_interface__], out_shape=shape2, transform=tr, invert=True, all_touched=False)
                denom = int(pmask.sum())
                arr = {kind: ds.read(1, window=w, masked=False).astype(float) for kind, ds in dsmap.items()}
                valid = pmask.copy()
                for kind, ds in dsmap.items():
                    valid &= valid_mask(arr[kind], ds.nodata)
                nv = int(valid.sum())
                base["soil_pixels_total"] = denom
                base["soil_pixels_valid"] = nv
                base["soil_coverage_pct"] = 100.0 * nv / denom if denom else 0.0
                if nv:
                    for kind in ("clay", "silt", "sand"):
                        v = arr[kind][valid]
                        base[f"{kind}_mean_pct"] = float(np.mean(v))
                        base[f"{kind}_sd_pct"] = float(np.std(v, ddof=0))
                        base[f"{kind}_p10_pct"] = float(np.percentile(v, 10))
                        base[f"{kind}_p90_pct"] = float(np.percentile(v, 90))
                    tsum = arr["clay"][valid] + arr["silt"][valid] + arr["sand"][valid]
                    base["texture_sum_mean_pct"] = float(np.mean(tsum))
                    base["texture_heterogeneity_rms"] = float(np.sqrt(np.mean([
                        base["clay_sd_pct"] ** 2, base["silt_sd_pct"] ** 2, base["sand_sd_pct"] ** 2,
                    ])))
                rows.append(base)
                if n % 500 == 0 or n == len(skiften):
                    print(f"  sampled {n:,}/{len(skiften):,}", flush=True)
    feat = pd.DataFrame(rows)
    feat.to_csv(outdir / "skifte_soil_features.csv", index=False, encoding="utf-8-sig")
    return feat


def safe_scale(x):
    x = np.asarray(x, float)
    med = np.nanmedian(x, axis=0)
    mad = np.nanmedian(np.abs(x - med), axis=0) * 1.4826
    std = np.nanstd(x, axis=0, ddof=0)
    scale = np.where(np.isfinite(mad) & (mad > 1e-9), mad, std)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return med, scale


def build_reference(train: pd.DataFrame):
    X = train[["clay_mean_pct", "silt_mean_pct"]].to_numpy(float)
    center, scale = safe_scale(X)
    Z = (X - center) / scale
    cov = np.cov(Z, rowvar=False, ddof=1) if len(Z) >= 3 else np.eye(2)
    if cov.shape != (2, 2) or not np.all(np.isfinite(cov)):
        cov = np.eye(2)
    cov = (1.0 - REGULARIZATION) * cov + REGULARIZATION * np.eye(2)
    inv_cov = np.linalg.pinv(cov)
    d_train = np.sqrt(np.einsum("ij,jk,ik->i", Z, inv_cov, Z))
    h_train = train["texture_heterogeneity_rms"].to_numpy(float)
    return {"center": center, "scale": scale, "inv_cov": inv_cov,
            "d_train": d_train[np.isfinite(d_train)], "h_train": h_train[np.isfinite(h_train)], "n": len(train)}


def survival_score(ref_values, value):
    a = np.asarray(ref_values, float)
    a = a[np.isfinite(a)]
    if not len(a) or not np.isfinite(value):
        return np.nan
    gt = np.sum(a > value)
    eq = np.sum(np.isclose(a, value, rtol=1e-10, atol=1e-12))
    return float(100.0 * (gt + 0.5 * eq) / len(a))


def score_with_reference(r, ref):
    x = np.array([r.clay_mean_pct, r.silt_mean_pct], float)
    z = (x - ref["center"]) / ref["scale"]
    d = float(np.sqrt(z @ ref["inv_cov"] @ z))
    h = float(r.texture_heterogeneity_rms)
    center_score = survival_score(ref["d_train"], d)
    hom_score = survival_score(ref["h_train"], h)
    combined = float(math.sqrt(max(center_score, 0.0) * max(hom_score, 0.0))) if np.isfinite(center_score) and np.isfinite(hom_score) else np.nan
    return d, h, center_score, hom_score, combined


def score_ferrari(feat: pd.DataFrame):
    d = feat.copy()
    needed = ["clay_mean_pct", "silt_mean_pct", "clay_sd_pct", "silt_sd_pct", "sand_sd_pct", "texture_heterogeneity_rms"]
    d["score_eligible"] = (
        d[needed].notna().all(axis=1)
        & d["soil_coverage_pct"].ge(MIN_SOIL_COVERAGE_PCT)
        & d["class_overlap_share"].ge(MIN_CLASS_OVERLAP_SHARE)
        & d["geom_area_ha"].ge(MIN_SKIFTE_HA)
    )
    train_all = d[d["score_eligible"] & d["historic_class"].eq(10)].copy()
    if len(train_all) < MIN_TRAIN_N:
        raise RuntimeError(f"Too few eligible class-10 skiften for Ferrari reference: {len(train_all)}")
    print(f"Eligible class-10 reference skiften: {len(train_all):,}")
    cache = {}
    for c, v in {
        "texture_center_distance": np.nan, "texture_heterogeneity_rms_scored": np.nan,
        "texture_center_score": np.nan, "homogeneity_score": np.nan, "ferrari_score": np.nan,
        "reference_n": np.nan, "reference_mode": "",
    }.items():
        d[c] = v
    eligible = d[d["score_eligible"]].copy()
    for n, (idx, r) in enumerate(eligible.iterrows(), 1):
        cell = str(r.spatial_cell)
        if cell not in cache:
            train = train_all[train_all["spatial_cell"].ne(cell)].copy()
            mode = "leave_10km_cell_out"
            if len(train) < MIN_TRAIN_N:
                train = train_all.copy()
                mode = "fallback_all_class10"
            cache[cell] = (build_reference(train), mode)
        ref, mode = cache[cell]
        dist, h, cs, hs, fs = score_with_reference(r, ref)
        d.at[idx, "texture_center_distance"] = dist
        d.at[idx, "texture_heterogeneity_rms_scored"] = h
        d.at[idx, "texture_center_score"] = cs
        d.at[idx, "homogeneity_score"] = hs
        d.at[idx, "ferrari_score"] = fs
        d.at[idx, "reference_n"] = ref["n"]
        d.at[idx, "reference_mode"] = mode
        if n % 2000 == 0 or n == len(eligible):
            print(f"  scored {n:,}/{len(eligible):,}", flush=True)
    oof10 = d[d["score_eligible"] & d["historic_class"].eq(10) & d["ferrari_score"].notna()].copy()
    threshold = float(np.quantile(oof10["ferrari_score"], CLASS10_KEEP_QUANTILE))
    d["ferrari_threshold"] = threshold
    d["ferrari_like"] = d["score_eligible"] & d["ferrari_score"].ge(threshold)
    d["diagnostic_group"] = "not_scored"
    d.loc[d["score_eligible"], "diagnostic_group"] = "other_scored"
    d.loc[d["score_eligible"] & d["historic_class"].eq(10) & d["ferrari_like"], "diagnostic_group"] = "true_ferrari"
    d.loc[d["score_eligible"] & d["historic_class"].eq(10) & ~d["ferrari_like"], "diagnostic_group"] = "non_ferrari_inside_class10"
    d.loc[d["score_eligible"] & d["historic_class"].lt(10) & d["ferrari_like"], "diagnostic_group"] = "ferrari_outside_class10"
    return d, threshold, train_all


def class_summary(scored):
    rows = []
    for k in range(CLASS_MIN, CLASS_MAX + 1):
        q = scored[scored["historic_class"].eq(k)]
        e = q[q["score_eligible"]]
        f = e[e["ferrari_like"]]
        rows.append({
            "historic_class": k, "n_skiften": len(q), "n_eligible": len(e), "n_ferrari_like": len(f),
            "ferrari_like_share_pct": 100.0 * len(f) / len(e) if len(e) else np.nan,
            "ferrari_score_median": float(e["ferrari_score"].median()) if len(e) else np.nan,
            "ferrari_score_p90": float(e["ferrari_score"].quantile(0.90)) if len(e) else np.nan,
            "clay_mean_median_pct": float(e["clay_mean_pct"].median()) if len(e) else np.nan,
            "heterogeneity_median": float(e["texture_heterogeneity_rms"].median()) if len(e) else np.nan,
        })
    return pd.DataFrame(rows)


def escape_json_for_html(s: str):
    return s.replace("</", "<\\/")


def build_html_map(scored_gdf, dissolved, outpath, threshold):
    outside = scored_gdf[scored_gdf["diagnostic_group"].eq("ferrari_outside_class10")].copy()
    inside_bad = scored_gdf[scored_gdf["diagnostic_group"].eq("non_ferrari_inside_class10")].copy()
    def prep(g):
        z = g.to_crs(3006).copy()
        if not z.empty:
            z["geometry"] = z.geometry.simplify(4.0, preserve_topology=True)
        z = z.to_crs(4326)
        keep = ["blockid","skiftesbeteckning","historic_class","geom_area_ha","class_overlap_share",
                "soil_coverage_pct","clay_mean_pct","silt_mean_pct","sand_mean_pct","clay_sd_pct",
                "silt_sd_pct","sand_sd_pct","texture_center_score","homogeneity_score","ferrari_score",
                "diagnostic_group","geometry"]
        return z[[c for c in keep if c in z.columns]]
    outside = prep(outside)
    inside_bad = prep(inside_bad)
    cls = dissolved.to_crs(4326).copy()
    cls["geometry"] = cls.geometry.simplify(20, preserve_topology=True)
    gj_out = escape_json_for_html(outside.to_json(drop_id=True))
    gj_bad = escape_json_for_html(inside_bad.to_json(drop_id=True))
    gj_cls = escape_json_for_html(cls[["KLASS","geometry"]].to_json(drop_id=True))
    bounds = cls.total_bounds.tolist()
    html = f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ÅkerSync · Ferrari-skiften v0c</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><style>html,body,#map{{height:100%;margin:0}} .box{{background:white;padding:9px 11px;border-radius:7px;box-shadow:0 1px 6px #777;font:13px Arial;max-width:390px}} .legend i{{display:inline-block;width:13px;height:13px;margin-right:6px;vertical-align:-2px}}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const classes={gj_cls}; const outside={gj_out}; const bad={gj_bad}; const map=L.map('map');
const osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OpenStreetMap'}}).addTo(map);
const esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:'Esri'}});
const classColors={{5:'#ffffbf',6:'#fee090',7:'#fdae61',8:'#f46d43',9:'#d73027',10:'#7f0000'}};
const clsLayer=L.geoJSON(classes,{{style:f=>({{color:classColors[f.properties.KLASS]||'#777',weight:f.properties.KLASS===10?2.5:1.0,fillOpacity:0.02}}),onEachFeature:(f,l)=>l.bindTooltip('Historisk klass '+f.properties.KLASS)}}).addTo(map);
function popup(p){{return `<b>Skifte ${{p.skiftesbeteckning||''}}</b><br>Block ${{p.blockid||''}}<br>Historisk klass: <b>${{p.historic_class}}</b><br>FerrariScore: <b>${{Number(p.ferrari_score).toFixed(1)}}</b><br>Center: ${{Number(p.texture_center_score).toFixed(1)}} · homogenitet: ${{Number(p.homogeneity_score).toFixed(1)}}<br>Lera/silt/sand: ${{Number(p.clay_mean_pct).toFixed(1)}} / ${{Number(p.silt_mean_pct).toFixed(1)}} / ${{Number(p.sand_mean_pct).toFixed(1)}} %<br>SD: ${{Number(p.clay_sd_pct).toFixed(1)}} / ${{Number(p.silt_sd_pct).toFixed(1)}} / ${{Number(p.sand_sd_pct).toFixed(1)}}<br>Klassöverlapp: ${{(100*Number(p.class_overlap_share)).toFixed(0)}}% · jordtäckning: ${{Number(p.soil_coverage_pct).toFixed(0)}}%`;}}
const outsideLayer=L.geoJSON(outside,{{style:{{color:'#006837',weight:2,fillColor:'#1a9850',fillOpacity:.55}},onEachFeature:(f,l)=>l.bindPopup(popup(f.properties))}}).addTo(map);
const badLayer=L.geoJSON(bad,{{style:{{color:'#3f007d',weight:2,fillColor:'#762a83',fillOpacity:.48}},onEachFeature:(f,l)=>l.bindPopup(popup(f.properties))}}).addTo(map);
L.control.layers({{'OpenStreetMap':osm,'Esri satellite':esri}},{{'Historiska klass 5–10':clsLayer,'Ferrari utanför klass 10':outsideLayer,'Icke-Ferrari inne i klass 10':badLayer}},{{collapsed:false}}).addTo(map);
map.fitBounds([[{bounds[1]},{bounds[0]}],[{bounds[3]},{bounds[2]}]]);
const info=L.control({{position:'topleft'}}); info.onAdd=()=>{{let d=L.DomUtil.create('div','box legend');d.innerHTML=`<b>ÅkerSync · Ferrari-skiften v0c</b><br>Jord-only diagnostik, spatial 10 km holdout.<br>Ferrari-tröskel: <b>{threshold:.1f}</b><br><br><i style="background:#1a9850"></i>Ferrari-lik jord utanför klass 10<br><i style="background:#762a83"></i>Icke-Ferrari-lik jord inne i klass 10<br><br>Klicka på skifte för jordprofil.`;return d;}}; info.addTo(map);
</script></body></html>'''
    outpath.write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    outdir = root / cfg.get("build_dir", "data/derived") / "agri_class5_10_v0c_ferrari"
    outdir.mkdir(parents=True, exist_ok=True)
    skiften_path = Path(cfg.get("skiften", ""))
    soil_zip = Path(cfg.get("soil_zip", ""))
    if not skiften_path.exists():
        raise FileNotFoundError(f"Skiftefil saknas: {skiften_path}")
    if not soil_zip.exists():
        raise FileNotFoundError(f"soil_zip saknas: {soil_zip}")
    print("=" * 92)
    print("ÅkerSync · skifte-level Ferrari soil experiment · v0c")
    print("=" * 92)
    print("SOIL ONLY. Climate/topography/hydrology intentionally excluded.")
    print("Output:", outdir)
    print()
    classes = load_classes(root, outdir, args.refresh)
    skiften = gpd.read_file(skiften_path).to_crs(3006)
    if "arslager" in skiften.columns:
        skiften = skiften[pd.to_numeric(skiften["arslager"], errors="coerce").eq(2025)].copy()
    skiften = skiften[skiften.geometry.notna() & ~skiften.geometry.is_empty].reset_index(drop=True)
    classified, dissolved = assign_historic_class(skiften, classes)
    print(f"2025 skiften with historic class 5–10: {len(classified):,}")
    print(classified["historic_class"].value_counts().sort_index().to_string())
    print()
    feat = sample_skiften_soil(classified, soil_zip, outdir)
    scored, threshold, train10 = score_ferrari(feat)
    summary = class_summary(scored)
    scored.to_csv(outdir / "skifte_ferrari_scores.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(outdir / "ferrari_by_historic_class.csv", index=False, encoding="utf-8-sig")
    outside = scored[scored["diagnostic_group"].eq("ferrari_outside_class10")].sort_values("ferrari_score", ascending=False)
    nonf = scored[scored["diagnostic_group"].eq("non_ferrari_inside_class10")].sort_values("ferrari_score", ascending=True)
    outside.to_csv(outdir / "ferrari_outside_class10.csv", index=False, encoding="utf-8-sig")
    nonf.to_csv(outdir / "non_ferrari_inside_class10.csv", index=False, encoding="utf-8-sig")
    geom_lookup = classified[["geometry"]].copy()
    scored_geo = scored.merge(geom_lookup, left_on="row_index", right_index=True, how="left")
    scored_geo = gpd.GeoDataFrame(scored_geo, geometry="geometry", crs=3006)
    gpkg = outdir / "ferrari_skifte_qa.gpkg"
    if gpkg.exists(): gpkg.unlink()
    scored_geo.to_file(gpkg, layer="all_scored_skiften", driver="GPKG")
    scored_geo[scored_geo["diagnostic_group"].eq("ferrari_outside_class10")].to_file(gpkg, layer="ferrari_outside_class10", driver="GPKG")
    scored_geo[scored_geo["diagnostic_group"].eq("non_ferrari_inside_class10")].to_file(gpkg, layer="non_ferrari_inside_class10", driver="GPKG")
    dissolved.to_file(gpkg, layer="historic_class5_10", driver="GPKG")
    build_html_map(scored_geo, dissolved, outdir / "ferrari_anomaly_map.html", threshold)
    lines = [
        "ÅkerSync · skifte-level Ferrari soil experiment · v0c", "=" * 78,
        f"Historic classes: {CLASS_MIN}–{CLASS_MAX}",
        f"Eligible rule: soil coverage ≥{MIN_SOIL_COVERAGE_PCT:.0f}%, class overlap ≥{100*MIN_CLASS_OVERLAP_SHARE:.0f}%, area ≥{MIN_SKIFTE_HA:.1f} ha",
        f"Spatial reference: leave own {GRID_M/1000:.0f} km grid cell out of class-10 reference",
        f"Eligible class-10 reference skiften: {len(train10):,}",
        f"Ferrari-like threshold = class-10 OOF P{100*CLASS10_KEEP_QUANTILE:.0f}: {threshold:.2f}", "", "BY HISTORIC CLASS",
    ]
    for _, r in summary.iterrows():
        lines.append(f"  Class {int(r.historic_class)}: eligible {int(r.n_eligible):,}; Ferrari-like {int(r.n_ferrari_like):,} ({r.ferrari_like_share_pct:.1f}%); median score {r.ferrari_score_median:.1f}")
    lines += ["", f"Ferrari-like skiften OUTSIDE class 10: {len(outside):,}", f"Non-Ferrari skiften INSIDE class 10: {len(nonf):,}", "",
              "Interpretation:",
              "- A Ferrari-like outside-class-10 skifte has class-10-like SOIL, not proven class-10 production.",
              "- A non-Ferrari inside-class-10 skifte may be a true anomaly, a class-boundary artefact, or evidence that soil is not the whole story.",
              "- Climate, topography and hydrology are intentionally not used here; they are candidate explanations for the anomalies in a later stage.",
              "- DSMS2025 is a soil model. Spatial holdout reduces circularity but does not turn modeled pixels into independent measurements."]
    report = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(report, encoding="utf-8")
    meta = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "class_source": LAYER_URL,
        "class_filter": "KLASS 5–10", "soil_grid": "DSMS2025 20 m",
        "score_components": ["mean clay+silt center similarity", "within-skifte texture homogeneity"],
        "combined_score": "sqrt(texture_center_score * homogeneity_score)", "spatial_holdout_m": GRID_M,
        "eligible": {"soil_coverage_pct_min": MIN_SOIL_COVERAGE_PCT, "class_overlap_share_min": MIN_CLASS_OVERLAP_SHARE, "skifte_area_ha_min": MIN_SKIFTE_HA},
        "ferrari_threshold": threshold, "threshold_definition": f"P{100*CLASS10_KEEP_QUANTILE:.0f} of spatially held-out eligible class-10 FerrariScore",
    }
    (outdir / "method_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + report)
    print("Main outputs:")
    for fn in ["skifte_ferrari_scores.csv","ferrari_by_historic_class.csv","ferrari_outside_class10.csv","non_ferrari_inside_class10.csv","ferrari_anomaly_map.html","ferrari_skifte_qa.gpkg","report.txt"]:
        print(" ", outdir / fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
