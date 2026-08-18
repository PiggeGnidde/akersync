#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync agricultural class 5-10 soil profile experiment (v0b).

Extends the class 9/10 prototype to classes 5,6,7,8,9,10 using the same
ArcGIS polygon source and the same DSMS2025 layers.

Outputs class-wise summaries for:
A) the full historic class polygon area; and
B) the part that still lies inside 2025 agricultural blocks.
"""
from __future__ import annotations
import argparse, json, math, tempfile, urllib.parse, urllib.request, zipfile
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
OFFICIAL_INFO_URL = "https://www.lansstyrelsen.se/skane/natur-och-landsbygd/information-till-verksamma-pa-landsbygden/forvarv-av-lantbruksfastigheter.html"
SOIL_MEMBERS = {
    "clay": "dsms2025_ler.tif",
    "sand": "dsms2025_sand.tif",
    "silt": "dsms2025_silt.tif",
    "organic": "dsms2025_organisk_klasser.tif",
}
ORG_CODES = [2, 3, 4, 5, 6, 9, 16, 30]
ORG_LABELS = {
    2: "<2,5 %",
    3: "2,5–3,5 %",
    4: "3,5–4,5 %",
    5: "4,5–5,5 %",
    6: "5,5–6,5 %",
    9: "6,5–12 %",
    16: "12–20 %",
    30: "≥20 %",
}
POPULATIONS = ("historic_class_area", "current_2025_farmland")


def arcgis_get(params, timeout=120):
    url = QUERY_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download_class_polygons(class_min: int = 5, class_max: int = 10):
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
        raise RuntimeError("No class polygons returned from ArcGIS service.")
    rows, geoms = [], []
    for f in features:
        p = f.get("properties", {})
        rows.append({"OBJECTID_12": p.get("OBJECTID_12"), "KLASS": p.get("KLASS")})
        geoms.append(shape(f.get("geometry")))
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)
    gdf["KLASS"] = pd.to_numeric(gdf["KLASS"], errors="coerce").astype("Int64")
    gdf = gdf[gdf["KLASS"].between(class_min, class_max) & gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    return gdf.to_crs(3006)


def load_or_download_source(cache, refresh, class_min=5, class_max=10):
    if cache.exists() and not refresh:
        print("Using cached class polygons:", cache)
        gdf = gpd.read_file(cache, layer="class5_10").to_crs(3006)
    else:
        print(f"Downloading historic class polygons {class_min}-{class_max}...")
        gdf = download_class_polygons(class_min, class_max)
        cache.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(cache, layer="class5_10", driver="GPKG")
        print("Cached:", cache)
    return gdf


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


def polygon_parts(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return [g for g in geom.geoms if not g.is_empty]
    try:
        return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    except Exception:
        return []


def stats(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not len(v):
        return {k: np.nan for k in ["mean", "sd", "p10", "p25", "p50", "p75", "p90"]}
    q = np.percentile(v, [10, 25, 50, 75, 90])
    return {
        "mean": float(v.mean()),
        "sd": float(v.std(ddof=0)),
        "p10": float(q[0]),
        "p25": float(q[1]),
        "p50": float(q[2]),
        "p75": float(q[3]),
        "p90": float(q[4]),
    }


def summarize_texture(x, row):
    for j, name in enumerate(["clay", "silt", "sand"]):
        for k, v in stats(x[:, j] if len(x) else np.array([])).items():
            row[f"{name}_{k}_pct"] = v
    tsum = x.sum(axis=1) if len(x) else np.array([])
    for k, v in stats(tsum).items():
        row[f"texture_sum_{k}_pct"] = v
    return row


def sample(classes, blocks, soil_zip, outdir):
    class_ids = sorted(pd.to_numeric(classes["KLASS"], errors="coerce").dropna().astype(int).unique().tolist())
    cls = classes[["KLASS", "geometry"]].dissolve(by="KLASS").reset_index()
    cls["KLASS"] = cls["KLASS"].astype(int)
    blocks = blocks.to_crs(3006).copy()
    blocks = blocks[blocks.geometry.notna() & ~blocks.geometry.is_empty].reset_index(drop=True)
    sidx = blocks.sindex

    store = {(k, p): {"tex": [], "org": [], "mask_n": 0} for k in class_ids for p in POPULATIONS}

    with tempfile.TemporaryDirectory(prefix="akersync_class510_") as td, zipfile.ZipFile(soil_zip) as zf:
        paths = {kind: extract_member(zf, base, td) for kind, base in SOIL_MEMBERS.items()}
        with rasterio.open(paths["clay"]) as clay, rasterio.open(paths["silt"]) as silt, rasterio.open(paths["sand"]) as sand, rasterio.open(paths["organic"]) as organic:
            dsmap = {"clay": clay, "silt": silt, "sand": sand, "organic": organic}
            ref = clay
            for kind, ds in dsmap.items():
                if not crs_is_3006(ds.crs):
                    raise RuntimeError(f"{paths[kind].name}: expected SWEREF99 TM/EPSG:3006, got {ds.crs}")
                if tuple(round(x, 6) for x in ds.res) != (20.0, 20.0):
                    raise RuntimeError(f"{paths[kind].name}: expected 20m pixels, got {ds.res}")
                if ds.width != ref.width or ds.height != ref.height or ds.transform != ref.transform:
                    raise RuntimeError(f"{paths[kind].name}: raster grid does not align with clay raster")
            pixel_area_ha = abs(ref.transform.a * ref.transform.e) / 10000.0
            for _, rr in cls.sort_values("KLASS").iterrows():
                klass = int(rr.KLASS)
                parts = polygon_parts(rr.geometry)
                print(f"Class {klass}: {len(parts)} polygon parts")
                for ip, part in enumerate(parts, 1):
                    w = geom_window(ref, part)
                    if w is None:
                        continue
                    tr = ref.window_transform(w)
                    shape2 = (int(w.height), int(w.width))
                    class_mask = geometry_mask([part.__geo_interface__], out_shape=shape2, transform=tr, invert=True, all_touched=False)
                    if not class_mask.any():
                        continue
                    try:
                        idx = list(sidx.query(part, predicate="intersects"))
                    except Exception:
                        idx = list(sidx.query(part))
                    block_geoms = [g for g in blocks.iloc[idx].geometry if g is not None and not g.is_empty]
                    farm_mask = geometry_mask([g.__geo_interface__ for g in block_geoms], out_shape=shape2, transform=tr, invert=True, all_touched=False) if block_geoms else np.zeros(shape2, dtype=bool)
                    arr = {kind: ds.read(1, window=w, masked=False).astype(float) for kind, ds in dsmap.items()}
                    tex_valid = valid_mask(arr["clay"], clay.nodata) & valid_mask(arr["silt"], silt.nodata) & valid_mask(arr["sand"], sand.nodata)
                    org_valid = valid_mask(arr["organic"], organic.nodata)
                    for pop, pmask in [("historic_class_area", class_mask), ("current_2025_farmland", class_mask & farm_mask)]:
                        d = store[(klass, pop)]
                        d["mask_n"] += int(pmask.sum())
                        mt = pmask & tex_valid
                        mo = pmask & org_valid
                        if mt.any():
                            d["tex"].append(np.column_stack([arr["clay"][mt], arr["silt"][mt], arr["sand"][mt]]))
                        if mo.any():
                            d["org"].append(arr["organic"][mo].astype(int))
                    if ip % 100 == 0:
                        print(f"  processed {ip}/{len(parts)} parts", flush=True)

    summary_rows, cov_rows, org_rows = [], [], []
    for klass in class_ids:
        exact_area = float(cls.loc[cls.KLASS.eq(klass), "geometry"].iloc[0].area) / 10000.0
        for pop in POPULATIONS:
            d = store[(klass, pop)]
            x = np.concatenate(d["tex"], axis=0) if d["tex"] else np.empty((0, 3), float)
            org = np.concatenate(d["org"]) if d["org"] else np.array([], int)
            row = {
                "klass": klass,
                "population": pop,
                "historic_polygon_area_ha": exact_area,
                "mask_pixels": d["mask_n"],
                "mask_pixel_area_ha": d["mask_n"] * pixel_area_ha,
                "texture_valid_pixels": len(x),
                "texture_coverage_pct": 100.0 * len(x) / d["mask_n"] if d["mask_n"] else np.nan,
                "organic_valid_pixels": len(org),
                "organic_coverage_pct": 100.0 * len(org) / d["mask_n"] if d["mask_n"] else np.nan,
            }
            summary_rows.append(summarize_texture(x, row))
            if len(x) >= 2:
                cov = np.cov(x, rowvar=False, ddof=1)
                cor = np.corrcoef(x, rowvar=False)
                names = ["clay", "silt", "sand"]
                for i in range(3):
                    for j in range(i, 3):
                        cov_rows.append({
                            "klass": klass,
                            "population": pop,
                            "var1": names[i],
                            "var2": names[j],
                            "covariance_pct2": float(cov[i, j]),
                            "correlation": float(cor[i, j]),
                            "n": len(x),
                        })
            counts = {c: int(np.sum(org == c)) for c in ORG_CODES}
            orow = {"klass": klass, "population": pop, "n_pixels": len(org), "unknown_code_pixels": int(len(org) - sum(counts.values()))}
            for c in ORG_CODES:
                orow[f"share_code_{c}_pct"] = 100.0 * counts[c] / len(org) if len(org) else np.nan
                orow[f"label_code_{c}"] = ORG_LABELS[c]
            org_rows.append(orow)

    sdf = pd.DataFrame(summary_rows)
    cdf = pd.DataFrame(cov_rows)
    odf = pd.DataFrame(org_rows)

    current = sdf[sdf["population"] == "current_2025_farmland"].sort_values("klass").copy()
    current["clay_sd_vs_class10_ratio"] = current["clay_sd_pct"] / float(current.loc[current["klass"] == 10, "clay_sd_pct"].iloc[0])
    current["silt_sd_vs_class10_ratio"] = current["silt_sd_pct"] / float(current.loc[current["klass"] == 10, "silt_sd_pct"].iloc[0])
    current["sand_sd_vs_class10_ratio"] = current["sand_sd_pct"] / float(current.loc[current["klass"] == 10, "sand_sd_pct"].iloc[0])
    current.to_csv(outdir / "class5_10_gradient_current_farmland.csv", index=False, encoding="utf-8-sig")

    sdf.to_csv(outdir / "class5_10_soil_summary.csv", index=False, encoding="utf-8-sig")
    cdf.to_csv(outdir / "class5_10_texture_covariance.csv", index=False, encoding="utf-8-sig")
    odf.to_csv(outdir / "class5_10_organic_summary.csv", index=False, encoding="utf-8-sig")
    return sdf, cdf, odf, cls


def report_text(sdf, source_n):
    current = sdf[sdf["population"] == "current_2025_farmland"].sort_values("klass")
    lines = [
        "ÅkerSync · Agricultural class 5–10 soil profile · v0b",
        "=" * 76,
        f"Downloaded source polygons: {source_n}",
        "Sampling unit: DSMS2025 20x20 m pixels, area-weighted by pixel.",
        "Municipalities are NOT averaged; class polygons define the population.",
        "Population A = full historic class polygon area.",
        "Population B = historic class pixels still inside 2025 agricultural blocks.",
        "",
        "CURRENT 2025 FARMLAND · CLASS GRADIENT",
    ]
    for _, q in current.iterrows():
        lines.append(
            f"  Class {int(q.klass)}: area≈{q.mask_pixel_area_ha:,.0f} ha; "
            f"clay mean/median={q.clay_mean_pct:.1f}/{q.clay_p50_pct:.1f}% (sd {q.clay_sd_pct:.1f}); "
            f"silt median={q.silt_p50_pct:.1f}%; sand median={q.sand_p50_pct:.1f}%; "
            f"texture coverage={q.texture_coverage_pct:.1f}%"
        )
    lines += [
        "",
        "Interpretation guardrails:",
        "- The 1970 classification is a historic production/harvest class, not a soil-texture class.",
        "- DSMS2025 describes modern mapped topsoil properties; this is an overlay across time.",
        "- Neighboring 20m pixels are spatially correlated and are not independent samples.",
        "- Use the pixel population to describe distributions; use spatial block bootstrap later for uncertainty.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--class-min", type=int, default=5)
    ap.add_argument("--class-max", type=int, default=10)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    outdir = root / cfg.get("build_dir", "data/derived") / "agri_class5_10_v0b"
    outdir.mkdir(parents=True, exist_ok=True)
    cache = outdir / "source" / "jord_skogsklassificering_class5_10.gpkg"

    print("=" * 88)
    print("ÅkerSync · Agricultural class 5–10 soil profile · v0b")
    print("=" * 88)
    print("Output:", outdir)
    print("Source layer:", LAYER_URL)
    print()

    blocks_path = Path(cfg.get("blocks", ""))
    soil_zip = Path(cfg.get("soil_zip", ""))
    if not blocks_path.exists():
        raise FileNotFoundError(f"Blockfil saknas: {blocks_path}")
    if not soil_zip.exists():
        raise FileNotFoundError(f"soil_zip saknas: {soil_zip}")

    classes = load_or_download_source(cache, args.refresh, args.class_min, args.class_max)
    klasses = sorted(pd.to_numeric(classes.KLASS, errors="coerce").dropna().astype(int).unique().tolist())
    print("Source polygons:", len(classes), "| classes:", klasses)

    blocks = gpd.read_file(blocks_path).to_crs(3006)
    mask_union = classes.geometry.union_all() if hasattr(classes.geometry, "union_all") else classes.geometry.unary_union
    try:
        idx = list(blocks.sindex.query(mask_union, predicate="intersects"))
    except Exception:
        idx = list(blocks.sindex.query(mask_union))
    qb = blocks.iloc[idx].copy()
    qpath = outdir / "qa_class5_10_and_current_blocks.gpkg"
    if qpath.exists():
        qpath.unlink()
    classes.to_file(qpath, layer="historic_class5_10", driver="GPKG")
    qb.to_file(qpath, layer="current_2025_blocks_near_class5_10", driver="GPKG")

    sdf, cdf, odf, dissolved = sample(classes, blocks, soil_zip, outdir)
    dissolved.to_file(outdir / "class5_10_dissolved.gpkg", layer="class5_10", driver="GPKG")

    metadata = {
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "feature_layer": LAYER_URL,
        "filter": f"KLASS >= {args.class_min} AND KLASS <= {args.class_max}",
        "source_note": "Ystad ArcGIS mirror; layer description states former LstM M-lan and L-lan classification.",
        "official_lansstyrelsen_reference": OFFICIAL_INFO_URL,
        "target_crs": "EPSG:3006",
        "soil_grid": "DSMS2025 20 m",
        "current_farmland_proxy": str(blocks_path),
    }
    (outdir / "source_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    rep = report_text(sdf, len(classes))
    (outdir / "report.txt").write_text(rep, encoding="utf-8")
    print("\n" + rep)
    print("QA map:", qpath)
    print("Output:", outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
