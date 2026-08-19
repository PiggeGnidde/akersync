#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync · Ferrari anomaly terrain contrast · v0e.

One run, two analyses:

A) Targeted natural experiment
   - Vollsjö: super-Ferrari soil analogues outside historic class 10
   - Bjärred/Lomma: extreme non-Ferrari skiften inside historic class 10
   - local controls around each area

B) Global held-out contrast
   - all super-Ferrari outside class 10 (v0d P90)
   - all extreme non-Ferrari inside class 10 (v0d P05)
   - compare topography and, if existing whole-area Whitebox rasters are found,
     hydrology/TWI.

IMPORTANT: soil/Ferrari classification is frozen from v0c/v0d. Terrain and
hydrology are added only now as candidate explanations; they do not alter the
Ferrari selection.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.windows import Window, from_bounds
from scipy.stats import mannwhitneyu
from shapely.geometry import Point

from common import load_config

V0C_DIRNAME = "agri_class5_10_v0c_ferrari"
V0D_DIRNAME = "agri_class5_10_v0d_extremes"
OUT_DIRNAME = "agri_class5_10_v0e_terrain_contrast"

VOLLSJO_LONLAT = (13.79, 55.70)
VOLLSJO_RADIUS_KM = 22.0
BJARRED_LONLAT = (13.02, 55.72)
BJARRED_RADIUS_KM = 18.0
LOCAL_CONTROL_MAX_N = 300
SEED = 20260818

TOPO_RES_M = 5.0
TOPO_CONTEXT_BUFFER_M = 500.0


def representative_xy(g: gpd.GeoDataFrame):
    rp = g.geometry.representative_point()
    return rp.x.to_numpy(float), rp.y.to_numpy(float)


def lonlat_to_3006(lon: float, lat: float) -> tuple[float, float]:
    s = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(3006)
    p = s.iloc[0]
    return float(p.x), float(p.y)


def attach_geometry(scores: pd.DataFrame, skiften_path: Path) -> gpd.GeoDataFrame:
    skiften = gpd.read_file(skiften_path).to_crs(3006)
    if "arslager" in skiften.columns:
        skiften = skiften[pd.to_numeric(skiften["arslager"], errors="coerce").eq(2025)].copy()
    skiften = skiften[skiften.geometry.notna() & ~skiften.geometry.is_empty].reset_index(drop=True)
    d = scores.copy()
    d["row_index"] = pd.to_numeric(d["row_index"], errors="coerce")
    bad = d["row_index"].isna() | d["row_index"].lt(0) | d["row_index"].ge(len(skiften))
    if bad.any():
        raise RuntimeError(f"{int(bad.sum())} score rows have invalid row_index for current skifte file")
    d["row_index"] = d["row_index"].astype(int)
    geoms = skiften.geometry.iloc[d["row_index"].to_numpy()].reset_index(drop=True)
    return gpd.GeoDataFrame(d.reset_index(drop=True), geometry=geoms, crs=3006)


def deterministic_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    if len(df) <= n:
        return df.copy()
    return df.sample(n=n, random_state=seed).copy()


def select_groups(scored_g: gpd.GeoDataFrame, outside_ids: set[int], inside_ids: set[int]):
    d = scored_g.copy()
    x, y = representative_xy(d)
    d["rep_x"] = x
    d["rep_y"] = y
    vx, vy = lonlat_to_3006(*VOLLSJO_LONLAT)
    bx, by = lonlat_to_3006(*BJARRED_LONLAT)
    d["dist_vollsjo_km"] = np.hypot(d.rep_x - vx, d.rep_y - vy) / 1000.0
    d["dist_bjarred_km"] = np.hypot(d.rep_x - bx, d.rep_y - by) / 1000.0

    d["is_super_outside"] = d["row_index"].isin(outside_ids)
    d["is_extreme_inside"] = d["row_index"].isin(inside_ids)
    eligible = d["score_eligible"].fillna(False).astype(bool)
    hist = pd.to_numeric(d["historic_class"], errors="coerce")

    voll_target = d[d.is_super_outside & d.dist_vollsjo_km.le(VOLLSJO_RADIUS_KM)].copy()
    voll_control_pool = d[
        eligible & hist.between(5, 9)
        & d.dist_vollsjo_km.le(VOLLSJO_RADIUS_KM)
        & ~d.is_super_outside
    ].copy()
    voll_control = deterministic_sample(voll_control_pool, LOCAL_CONTROL_MAX_N, SEED + 1)

    bjar_target = d[d.is_extreme_inside & d.dist_bjarred_km.le(BJARRED_RADIUS_KM)].copy()
    bjar_control_pool = d[
        eligible & hist.eq(10)
        & d.dist_bjarred_km.le(BJARRED_RADIUS_KM)
        & ~d.is_extreme_inside
    ].copy()
    bjar_control = deterministic_sample(bjar_control_pool, LOCAL_CONTROL_MAX_N, SEED + 2)

    groups = []
    for name, q in [
        ("Vollsjo_superFerrari", voll_target),
        ("Vollsjo_local_control_class5_9", voll_control),
        ("Bjarred_extreme_nonFerrari", bjar_target),
        ("Bjarred_local_class10_control", bjar_control),
    ]:
        z = q.copy()
        z["analysis_group"] = name
        groups.append(z)
    targeted = gpd.GeoDataFrame(pd.concat(groups, ignore_index=True), geometry="geometry", crs=3006)

    global_out = d[d.is_super_outside].copy()
    global_out["analysis_group"] = "Global_superFerrari_outside10"
    global_in = d[d.is_extreme_inside].copy()
    global_in["analysis_group"] = "Global_extreme_nonFerrari_inside10"
    global_groups = gpd.GeoDataFrame(pd.concat([global_out, global_in], ignore_index=True), geometry="geometry", crs=3006)

    all_selected = gpd.GeoDataFrame(pd.concat([targeted, global_groups], ignore_index=True), geometry="geometry", crs=3006)
    all_selected = all_selected.drop_duplicates(subset=["row_index"], keep="first")
    return targeted, global_groups, all_selected, {
        "vollsjo_center_3006": (vx, vy), "bjarred_center_3006": (bx, by),
        "vollsjo_control_pool_n": len(voll_control_pool), "bjarred_control_pool_n": len(bjar_control_pool),
    }


def finite_percentile(v, q):
    a = np.asarray(v, float)
    a = a[np.isfinite(a)]
    return float(np.percentile(a, q)) if a.size else np.nan


def pct(a):
    a = np.asarray(a)
    return float(100.0 * np.mean(a)) if a.size else np.nan


class DemTileIndex:
    def __init__(self, folder: Path):
        self.folder = folder
        self.records = []
        paths = sorted(folder.glob("*.tif"))
        if not paths:
            raise RuntimeError(f"Inga DEM .tif hittades i {folder}")
        px = []
        print(f"Indexing {len(paths):,} DEM tiles...")
        for p in paths:
            try:
                with rasterio.open(p) as ds:
                    if ds.crs is None or ds.crs.to_epsg() not in (3006, 5845):
                        continue
                    b = ds.bounds
                    self.records.append((b.left, b.bottom, b.right, b.top, p))
                    px.append(abs(ds.transform.a))
            except rasterio.errors.RasterioIOError:
                continue
        if not self.records:
            raise RuntimeError("Inga läsbara SWEREF99/RH2000 DEM tiles hittades")
        self.source_pixel_m = float(np.median(px)) if px else np.nan
        print(f"Indexed readable DEM tiles: {len(self.records):,}; source pixel ≈ {self.source_pixel_m:.2f} m")

    def intersecting_paths(self, bounds):
        minx, miny, maxx, maxy = bounds
        return [p for l, b, r, t, p in self.records if r > minx and l < maxx and t > miny and b < maxy]

    def read_mosaic(self, bounds, res=TOPO_RES_M):
        minx, miny, maxx, maxy = bounds
        ab = (
            math.floor(minx / res) * res,
            math.floor(miny / res) * res,
            math.ceil(maxx / res) * res,
            math.ceil(maxy / res) * res,
        )
        paths = self.intersecting_paths(ab)
        if not paths:
            return None, None, 0
        srcs = [rasterio.open(p) for p in paths]
        try:
            arr, tr = merge(
                srcs, bounds=ab, res=(res, res), resampling=Resampling.average,
                nodata=np.nan, dtype="float32", masked=False, method="first"
            )
            a = arr[0].astype(np.float32)
            a[~np.isfinite(a)] = np.nan
            return a, tr, len(paths)
        finally:
            for ds in srcs:
                ds.close()


def topo_features(geom, tiles: DemTileIndex):
    if geom is None or geom.is_empty:
        return {}
    context_geom = geom.buffer(TOPO_CONTEXT_BUFFER_M)
    dem, tr, ntile = tiles.read_mosaic(context_geom.bounds, TOPO_RES_M)
    if dem is None:
        return {"topo_coverage_pct": 0.0}
    valid = np.isfinite(dem)
    if not valid.any():
        return {"topo_coverage_pct": 0.0}

    inside = geometry_mask([geom.__geo_interface__], out_shape=dem.shape, transform=tr, invert=True, all_touched=False)
    context = geometry_mask([context_geom.__geo_interface__], out_shape=dem.shape, transform=tr, invert=True, all_touched=False)
    iv = inside & valid
    cv = context & valid
    ninside = int(inside.sum())
    ncontext = int(context.sum())
    z = dem[iv].astype(float)
    zc = dem[cv].astype(float)

    fill = float(np.nanmedian(dem))
    dfill = np.where(valid, dem, fill).astype(float)
    gy, gx = np.gradient(dfill, TOPO_RES_M, TOPO_RES_M)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    sv = slope[iv]
    sc = slope[cv]

    return {
        "topo_tile_count": ntile,
        "topo_coverage_pct": 100.0 * int(iv.sum()) / max(1, ninside),
        "context500_coverage_pct": 100.0 * int(cv.sum()) / max(1, ncontext),
        "elev_mean_m": float(np.mean(z)) if z.size else np.nan,
        "elev_sd_m": float(np.std(z)) if z.size else np.nan,
        "relief_p95_p05_m": finite_percentile(z, 95) - finite_percentile(z, 5) if z.size else np.nan,
        "slope_mean_deg": float(np.mean(sv)) if sv.size else np.nan,
        "slope_p50_deg": finite_percentile(sv, 50),
        "slope_p90_deg": finite_percentile(sv, 90),
        "slope_p95_deg": finite_percentile(sv, 95),
        "slope_lt_0p5_pct": pct(sv < 0.5) if sv.size else np.nan,
        "slope_lt_1_pct": pct(sv < 1.0) if sv.size else np.nan,
        "slope_gt_3_pct": pct(sv > 3.0) if sv.size else np.nan,
        "slope_gt_5_pct": pct(sv > 5.0) if sv.size else np.nan,
        "context500_elev_mean_m": float(np.mean(zc)) if zc.size else np.nan,
        "context500_relief_p95_p05_m": finite_percentile(zc, 95) - finite_percentile(zc, 5) if zc.size else np.nan,
        "context500_slope_mean_deg": float(np.mean(sc)) if sc.size else np.nan,
        "context500_slope_p90_deg": finite_percentile(sc, 90),
    }


def sample_topography(selected: gpd.GeoDataFrame, dem_dir: Path, cache_csv: Path):
    old = pd.read_csv(cache_csv) if cache_csv.exists() else pd.DataFrame()
    have = set(pd.to_numeric(old.get("row_index", pd.Series(dtype=float)), errors="coerce").dropna().astype(int).tolist())
    need = selected[~selected.row_index.astype(int).isin(have)].copy()
    if need.empty:
        print("Topography cache already covers all selected skiften.")
        return old
    tiles = DemTileIndex(dem_dir)
    rows = []
    print(f"Sampling topography for {len(need):,} new skiften...")
    for n, (_, r) in enumerate(need.iterrows(), 1):
        f = {"row_index": int(r.row_index)}
        f.update(topo_features(r.geometry, tiles))
        rows.append(f)
        if n % 100 == 0 or n == len(need):
            print(f"  topography {n:,}/{len(need):,}", flush=True)
    new = pd.DataFrame(rows)
    out = pd.concat([old, new], ignore_index=True) if not old.empty else new
    out = out.drop_duplicates("row_index", keep="last")
    out.to_csv(cache_csv, index=False, encoding="utf-8-sig")
    return out


def discover_hydrology_rasters(root: Path, cfg: dict):
    candidates = []
    wb = cfg.get("whitebox_work_dir")
    if wb:
        p = Path(wb)
        if p.exists(): candidates.append(p)
    build_dir = root / cfg.get("build_dir", "data/derived")
    if build_dir.exists():
        for txt in build_dir.rglob("hydrology_intermediate_files.txt"):
            try:
                for line in txt.read_text(encoding="utf-8-sig").splitlines():
                    p = Path(line.strip())
                    if p.exists(): candidates.append(p.parent)
            except Exception:
                pass
    dirs = []
    seen = set()
    for p in candidates:
        p = p.resolve()
        if str(p).casefold() not in seen:
            seen.add(str(p).casefold()); dirs.append(p)

    def choose(patterns):
        hits = []
        for d in dirs:
            for pat in patterns:
                hits.extend(d.glob(pat))
        hits = [p for p in hits if p.is_file()]
        hits = sorted(set(hits), key=lambda p: ("10m" in p.name.lower(), p.stat().st_size), reverse=True)
        return hits[0] if hits else None

    return {
        "twi": choose(["twi_10m.tif", "*twi*10m*.tif", "*twi*.tif"]),
        "sca": choose(["dinf_sca_10m.tif", "*sca*10m*.tif", "*sca*.tif"]),
        "hydro_slope": choose(["slope_10m_deg.tif", "*slope*10m*.tif"]),
    }


def vals_for_geom(ds, geom):
    try:
        w0 = from_bounds(*geom.bounds, transform=ds.transform)
    except Exception:
        return np.array([], float), 0.0
    c0 = max(0, int(math.floor(w0.col_off))); r0 = max(0, int(math.floor(w0.row_off)))
    c1 = min(ds.width, int(math.ceil(w0.col_off + w0.width))); r1 = min(ds.height, int(math.ceil(w0.row_off + w0.height)))
    if c1 <= c0 or r1 <= r0:
        return np.array([], float), 0.0
    w = Window(c0, r0, c1-c0, r1-r0)
    tr = ds.window_transform(w)
    inside = geometry_mask([geom.__geo_interface__], out_shape=(int(w.height), int(w.width)), transform=tr, invert=True, all_touched=False)
    a = ds.read(1, window=w, masked=False).astype(float)
    valid = inside & np.isfinite(a)
    if ds.nodata is not None: valid &= a != ds.nodata
    return a[valid], 100.0 * int(valid.sum()) / max(1, int(inside.sum()))


def sample_hydrology(selected: gpd.GeoDataFrame, rasters: dict, out_csv: Path):
    if not any(rasters.values()):
        print("No existing hydrology rasters found; topography analysis will still complete.")
        return pd.DataFrame({"row_index": selected.row_index.astype(int)})
    print("Hydrology rasters found:")
    for k, p in rasters.items(): print(f"  {k}: {p or 'NOT FOUND'}")
    datasets = {k: rasterio.open(p) for k, p in rasters.items() if p}
    try:
        rows = []
        for n, (_, r) in enumerate(selected.iterrows(), 1):
            q = {"row_index": int(r.row_index)}
            if "twi" in datasets:
                v, cov = vals_for_geom(datasets["twi"], r.geometry)
                q.update({
                    "twi_coverage_pct": cov,
                    "twi_mean": float(np.mean(v)) if v.size else np.nan,
                    "twi_sd": float(np.std(v)) if v.size else np.nan,
                    "twi_p50": finite_percentile(v, 50),
                    "twi_p90": finite_percentile(v, 90),
                    "twi_p95": finite_percentile(v, 95),
                })
            if "sca" in datasets:
                v, cov = vals_for_geom(datasets["sca"], r.geometry)
                q.update({
                    "sca_coverage_pct": cov,
                    "ln_sca_mean": float(np.mean(np.log(np.maximum(v, 1e-9)))) if v.size else np.nan,
                    "ln_sca_p90": finite_percentile(np.log(np.maximum(v, 1e-9)), 90) if v.size else np.nan,
                })
            rows.append(q)
            if n % 250 == 0 or n == len(selected):
                print(f"  hydrology {n:,}/{len(selected):,}", flush=True)
        out = pd.DataFrame(rows)
        out.to_csv(out_csv, index=False, encoding="utf-8-sig")
        return out
    finally:
        for ds in datasets.values(): ds.close()


def quantile_summary(df: pd.DataFrame, group_col: str, features: list[str]):
    rows = []
    for group, q in df.groupby(group_col, sort=False):
        for f in features:
            if f not in q.columns: continue
            x = pd.to_numeric(q[f], errors="coerce").dropna()
            if x.empty: continue
            rows.append({
                "group": group, "feature": f, "n": len(x),
                "mean": float(x.mean()), "sd": float(x.std(ddof=0)),
                "p25": float(x.quantile(.25)), "median": float(x.median()), "p75": float(x.quantile(.75)),
                "p10": float(x.quantile(.10)), "p90": float(x.quantile(.90)),
            })
    return pd.DataFrame(rows)


def rank_biserial(x, y):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    y = np.asarray(y, float); y = y[np.isfinite(y)]
    if not len(x) or not len(y): return np.nan
    u = mannwhitneyu(x, y, alternative="two-sided", method="auto").statistic
    return float(2.0 * u / (len(x) * len(y)) - 1.0)


def contrast_table(df: pd.DataFrame, g1: str, g2: str, features: list[str]):
    rows = []
    a = df[df.analysis_group.eq(g1)]
    b = df[df.analysis_group.eq(g2)]
    for f in features:
        if f not in df.columns: continue
        x = pd.to_numeric(a[f], errors="coerce").dropna().to_numpy(float)
        y = pd.to_numeric(b[f], errors="coerce").dropna().to_numpy(float)
        if not len(x) or not len(y): continue
        rows.append({
            "feature": f, "group1": g1, "group2": g2, "n1": len(x), "n2": len(y),
            "median1": float(np.median(x)), "median2": float(np.median(y)),
            "median_diff_1_minus_2": float(np.median(x) - np.median(y)),
            "rank_biserial_1_vs_2": rank_biserial(x, y),
        })
    out = pd.DataFrame(rows)
    if not out.empty: out = out.reindex(out.rank_biserial_1_vs_2.abs().sort_values(ascending=False).index)
    return out


def make_target_map(targeted: gpd.GeoDataFrame, outpath: Path):
    z = targeted.to_crs(3006).copy()
    z["geometry"] = z.geometry.simplify(4.0, preserve_topology=True)
    z = z.to_crs(4326)
    keep = ["analysis_group","historic_class","ferrari_score","blockid","skiftesbeteckning",
            "clay_mean_pct","silt_mean_pct","sand_mean_pct","geometry"]
    gj = z[[c for c in keep if c in z.columns]].to_json(drop_id=True).replace("</", "<\\/")
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ÅkerSync v0e targetområden</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{{height:100%;margin:0}}.box{{background:#fff;padding:8px;border-radius:6px;box-shadow:0 1px 5px #777;font:13px Arial}}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const data={gj}; const map=L.map('map').setView([55.7,13.4],9); const osm=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OpenStreetMap'}}).addTo(map); const esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:'Esri'}}); const colors={{'Vollsjo_superFerrari':'#6a3d9a','Vollsjo_local_control_class5_9':'#b2abd2','Bjarred_extreme_nonFerrari':'#00a6d6','Bjarred_local_class10_control':'#92c5de'}}; function pop(p){{return `<b>${{p.analysis_group}}</b><br>Klass ${{p.historic_class}} · FerrariScore ${{Number(p.ferrari_score).toFixed(1)}}<br>Block ${{p.blockid||''}} / skifte ${{p.skiftesbeteckning||''}}<br>Lera/silt/sand: ${{Number(p.clay_mean_pct).toFixed(1)}}/${{Number(p.silt_mean_pct).toFixed(1)}}/${{Number(p.sand_mean_pct).toFixed(1)}}`;}} const layer=L.geoJSON(data,{{style:f=>{{let c=colors[f.properties.analysis_group]||'#333';return {{color:c,weight:2,fillColor:c,fillOpacity:.5}}}},onEachFeature:(f,l)=>l.bindPopup(pop(f.properties))}}).addTo(map); if(layer.getBounds().isValid())map.fitBounds(layer.getBounds()); L.control.layers({{'OSM':osm,'Esri satellite':esri}},{{'A-targetgrupper':layer}},{{collapsed:false}}).addTo(map); const info=L.control({{position:'topleft'}});info.onAdd=()=>{{let d=L.DomUtil.create('div','box');d.innerHTML='<b>ÅkerSync v0e · A</b><br>Lila = Vollsjö super-Ferrari<br>Ljuslila = lokal kontroll<br>Turkos = Bjärred extrem non-Ferrari<br>Ljusblå = lokal klass-10 kontroll';return d}};info.addTo(map);
</script></body></html>'''
    outpath.write_text(html, encoding="utf-8")


def write_report(path: Path, targeted: pd.DataFrame, global_df: pd.DataFrame,
                 a_summary: pd.DataFrame, b_contrast: pd.DataFrame,
                 rasters: dict, meta: dict):
    lines = [
        "ÅkerSync · Ferrari anomaly terrain contrast · v0e",
        "=" * 78,
        "A = targeted Vollsjö vs Bjärred natural experiment",
        "B = global super-Ferrari outside class 10 vs extreme non-Ferrari inside class 10",
        "SOIL/Ferrari selection is frozen from v0c/v0d; terrain/hydrology are held-out candidate explanations.",
        "",
        "A · TARGETED GROUPS",
    ]
    for g, q in targeted.groupby("analysis_group", sort=False):
        lines.append(f"  {g}: n={len(q):,}")
    lines += [
        f"  Vollsjö diagnostic radius: {VOLLSJO_RADIUS_KM:.0f} km around {VOLLSJO_LONLAT[1]:.2f}N, {VOLLSJO_LONLAT[0]:.2f}E",
        f"  Bjärred diagnostic radius: {BJARRED_RADIUS_KM:.0f} km around {BJARRED_LONLAT[1]:.2f}N, {BJARRED_LONLAT[0]:.2f}E",
        f"  Vollsjö local-control pool before deterministic cap: {meta['vollsjo_control_pool_n']:,}",
        f"  Bjärred local-control pool before deterministic cap: {meta['bjarred_control_pool_n']:,}",
        "",
    ]
    pivot_feats = ["slope_mean_deg","slope_p90_deg","slope_lt_1_pct","relief_p95_p05_m","context500_relief_p95_p05_m","elev_mean_m","twi_mean","twi_p90"]
    if not a_summary.empty:
        for g in a_summary.group.unique():
            q = a_summary[a_summary.group.eq(g)].set_index("feature")
            lines.append(g)
            for f in pivot_feats:
                if f in q.index:
                    r=q.loc[f]; lines.append(f"    {f}: median {r['median']:.3f} (P25–P75 {r['p25']:.3f}–{r['p75']:.3f}, n={int(r['n'])})")
            lines.append("")
    lines += ["B · GLOBAL CONTRAST", f"  super-Ferrari outside class 10: n={int(global_df.analysis_group.eq('Global_superFerrari_outside10').sum()):,}", f"  extreme non-Ferrari inside class 10: n={int(global_df.analysis_group.eq('Global_extreme_nonFerrari_inside10').sum()):,}", ""]
    if not b_contrast.empty:
        lines.append("  Strongest descriptive rank-biserial contrasts (positive = larger in super-Ferrari outside):")
        for _, r in b_contrast.head(10).iterrows():
            lines.append(f"    {r.feature}: r_rb={r.rank_biserial_1_vs_2:+.3f}; medians {r.median1:.3f} vs {r.median2:.3f}")
    lines += ["", "HYDROLOGY INPUT", *[f"  {k}: {p if p else 'not found'}" for k,p in rasters.items()], "", "GUARDRAILS:", "- v0e is descriptive anomaly follow-up, not causal proof.", "- Spatially clustered skiften are not independent statistical replicates; no naive p-values are reported.", "- DEM-derived topography is independent of the soil-only Ferrari selection, but both may share geography.", "- TWI/SCA are used only if previously built whole-area rasters are found; no local catchment shortcut is invented.", "- If Vollsjö/Bjärred differences are large, next step is spatially matched modeling plus microclimate/coast exposure."]
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    build = root / cfg.get("build_dir", "data/derived")
    v0c = build / V0C_DIRNAME
    v0d = build / V0D_DIRNAME
    out = build / OUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)

    scores_path = v0c / "skifte_ferrari_scores.csv"
    outside_path = v0d / "super_ferrari_outside_class10.csv"
    inside_path = v0d / "extreme_non_ferrari_inside_class10.csv"
    skiften_path = Path(cfg.get("skiften", ""))
    dem_dir = Path(cfg.get("dem_dir", ""))
    for p, label in [(scores_path,"v0c score CSV"),(outside_path,"v0d super-Ferrari CSV"),(inside_path,"v0d extreme non-Ferrari CSV"),(skiften_path,"skiften GPKG")]:
        if not p.exists(): raise FileNotFoundError(f"{label} saknas: {p}")
    if not dem_dir.exists(): raise FileNotFoundError(f"DEM-mapp saknas: {dem_dir}")

    print("="*92); print("ÅkerSync · Ferrari anomaly terrain contrast · v0e"); print("="*92)
    print("A: Vollsjö vs Bjärred. B: global anomaly contrast. Soil selection stays frozen.")
    print("Output:", out); print()

    scores = pd.read_csv(scores_path)
    outside = pd.read_csv(outside_path)
    inside = pd.read_csv(inside_path)
    outside_ids = set(pd.to_numeric(outside.row_index, errors="coerce").dropna().astype(int))
    inside_ids = set(pd.to_numeric(inside.row_index, errors="coerce").dropna().astype(int))
    scored_g = attach_geometry(scores, skiften_path)
    targeted, global_groups, selected, meta = select_groups(scored_g, outside_ids, inside_ids)
    print("A targeted counts:")
    print(targeted.analysis_group.value_counts().to_string()); print()
    print("B global counts:")
    print(global_groups.analysis_group.value_counts().to_string()); print()

    topo = sample_topography(selected, dem_dir, out / "topography_selected_skiften_cache.csv")
    rasters = discover_hydrology_rasters(root, cfg)
    hydro = sample_hydrology(selected, rasters, out / "hydrology_selected_skiften.csv")

    def enrich(g):
        z = g.merge(topo, on="row_index", how="left", suffixes=("", "_topo"))
        z = z.merge(hydro, on="row_index", how="left", suffixes=("", "_hydro"))
        return z

    targeted_e = enrich(targeted.drop(columns="geometry"))
    global_e = enrich(global_groups.drop(columns="geometry"))
    targeted_e.to_csv(out / "A_vollsjo_bjarred_skiften.csv", index=False, encoding="utf-8-sig")
    global_e.to_csv(out / "B_global_anomaly_skiften.csv", index=False, encoding="utf-8-sig")

    topo_features_list = [
        "elev_mean_m","elev_sd_m","relief_p95_p05_m","slope_mean_deg","slope_p50_deg","slope_p90_deg","slope_p95_deg",
        "slope_lt_0p5_pct","slope_lt_1_pct","slope_gt_3_pct","slope_gt_5_pct",
        "context500_elev_mean_m","context500_relief_p95_p05_m","context500_slope_mean_deg","context500_slope_p90_deg",
    ]
    hydro_features = ["twi_mean","twi_sd","twi_p50","twi_p90","twi_p95","ln_sca_mean","ln_sca_p90"]
    soil_context = ["ferrari_score","texture_center_score","homogeneity_score","clay_mean_pct","silt_mean_pct","sand_mean_pct","texture_heterogeneity_rms"]
    features = soil_context + topo_features_list + hydro_features

    a_summary = quantile_summary(targeted_e, "analysis_group", features)
    a_summary.to_csv(out / "A_vollsjo_bjarred_summary.csv", index=False, encoding="utf-8-sig")
    a_contrast = contrast_table(targeted_e, "Vollsjo_superFerrari", "Bjarred_extreme_nonFerrari", features)
    a_contrast.to_csv(out / "A_vollsjo_vs_bjarred_contrast.csv", index=False, encoding="utf-8-sig")

    b_summary = quantile_summary(global_e, "analysis_group", features)
    b_summary.to_csv(out / "B_global_anomaly_summary.csv", index=False, encoding="utf-8-sig")
    b_contrast = contrast_table(global_e, "Global_superFerrari_outside10", "Global_extreme_nonFerrari_inside10", features)
    b_contrast.to_csv(out / "B_global_contrast.csv", index=False, encoding="utf-8-sig")

    make_target_map(targeted, out / "A_vollsjo_bjarred_map.html")
    write_report(out / "report.txt", targeted_e, global_e, a_summary, b_contrast, rasters, meta)

    print(); print("="*92); print("KLART"); print("="*92)
    print(out / "report.txt")
    print(out / "A_vollsjo_bjarred_summary.csv")
    print(out / "A_vollsjo_vs_bjarred_contrast.csv")
    print(out / "B_global_contrast.csv")
    print(out / "A_vollsjo_bjarred_map.html")
    if not rasters.get("twi"):
        print("NOTE: no existing TWI raster was found; v0e still completed with DEM topography.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
