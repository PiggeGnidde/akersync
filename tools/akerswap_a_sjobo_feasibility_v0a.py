from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

VERSION = "akerswap-a-sjobo-v0a"
SJÖBO_CODE = "1265"

RADII_M = (1000.0, 2000.0, 5000.0, 10000.0)
AREA_TOLS = (0.10, 0.20, 0.30)
SCORE_TOLS = (5.0, 10.0)
DRIFT_TOLS = (5.0, 10.0)
CORE = (0.20, 10.0, 10.0)
STRICT = (0.10, 5.0, 5.0)
ADJACENCY_M = 10.0

OUT = Path(r"C:\AkerSync-AkerAccess\work\akerswap_a_sjobo_v0a")

SKIFTE_CANDIDATES = [
    Path(r"C:\AkerSyncRaw\jv_skane_2025\arslager_skifte_skane_2025.gpkg"),
    Path(r"C:\AkerSyncRepo\data\raw\arslager_skifte.gpkg"),
]
BLOCK_CANDIDATES = [
    Path(r"C:\AkerSyncRaw\jv_skane_2025\arslager_block_skane_2025.gpkg"),
    Path(r"C:\AkerSyncRepo\data\raw\arslager_block.gpkg"),
]
SCORE_CANDIDATES = [
    Path(r"C:\AkerSyncRepo\data\derived\akerscore_soil_v0c\akerscore_soil_skiften.csv"),
    Path(r"C:\AkerSyncRepo\data\derived\akerscore_soil_v0c\akerscore_soil_skiften.gpkg"),
]
DRIFT_CANDIDATES = [
    Path(r"C:\AkerSyncRepo\data\derived\akerdrift_fast_v2_hybrid_rc1\akerdrift_fast_v2_hybrid_skane_fieldlevel.parquet"),
    Path(r"C:\AkerSyncRepo\data\derived\akerdrift_fast_v2_hybrid\akerdrift_fast_v2_hybrid_skane_fieldlevel.parquet"),
    Path(r"C:\AkerSyncRepo\data\derived\akerdrift_fast_v1\akerdrift_fast_v1_skane.parquet"),
]

def norm(x):
    s = "" if x is None else str(x)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")

def canon(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    parts = [x.strip() for x in s.split("|")]
    if len(parts) >= 3 and re.fullmatch(r"20\d{2}", parts[0]):
        s = "|".join(parts[1:])
    return s

def choose(cols, exact=(), token_sets=()):
    nm = {c: norm(c) for c in cols}
    for e in exact:
        en = norm(e)
        for c, n in nm.items():
            if n == en:
                return c
    for toks in token_sets:
        tt = [norm(t) for t in toks]
        hits = [c for c, n in nm.items() if all(t in n for t in tt)]
        if hits:
            return sorted(hits, key=lambda c: (len(nm[c]), nm[c]))[0]
    return None

def block_col(cols):
    return choose(cols, exact=("blockid", "block_id"), token_sets=(("block", "id"),))

def skifte_col(cols):
    return choose(
        cols,
        exact=("skiftesbeteckning", "skiftebeteckning", "skiftes_id", "skifte_id"),
        token_sets=(("skifte", "beteckning"),),
    )

def region_col(cols):
    return choose(
        cols,
        exact=("region_kod", "regionkod", "kommun_kod", "kommunkod"),
        token_sets=(("region", "kod"), ("kommun", "kod")),
    )

def field_col(cols):
    return choose(
        cols,
        exact=("field_key", "field_id", "current_field_id", "m0_field_id"),
        token_sets=(("field", "key"), ("field", "id")),
    )

def score_col(cols):
    return choose(
        cols,
        exact=("akerscore_soil_p50", "akerscore_p50", "akerscore", "aker_score", "score_p50"),
        token_sets=(("aker", "score", "p50"), ("akerscore", "p50"), ("aker", "score")),
    )

def drift_col(cols):
    return choose(
        cols,
        exact=("akerdrift_score", "akerdrift", "drift_score", "score_fast", "fast_score"),
        token_sets=(("aker", "drift", "score"), ("drift", "score")),
    )

def first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    return None

def read_table(path):
    s = path.suffix.lower()
    if s == ".parquet":
        return pd.read_parquet(path)
    if s == ".csv":
        return pd.read_csv(path, low_memory=False)
    if s == ".gpkg":
        return gpd.read_file(path)
    raise ValueError(path)

def derive_field_id(df):
    fc = field_col(df.columns)
    if fc:
        vals = df[fc].map(canon)
        if vals.astype(str).str.contains(r"\|").mean() > 0.5:
            return vals
    bc = block_col(df.columns)
    sc = skifte_col(df.columns)
    if bc and sc:
        return df[bc].map(canon) + "|" + df[sc].map(canon)
    if fc:
        return df[fc].map(canon)
    raise ValueError("Kan inte skapa field_id från kolumnerna.")

def metric_candidates(kind):
    base = SCORE_CANDIDATES if kind == "score" else DRIFT_CANDIDATES
    out = [p for p in base if p.exists()]
    roots = [
        Path(r"C:\AkerSyncRepo"),
        Path(r"C:\AkerSync-AkerAccess"),
        Path(r"C:\AkerSync-AkerScore"),
        Path(r"C:\AkerSync-AkerDrift"),
    ]
    needle = "score" if kind == "score" else "drift"
    seen = set(out)
    for root in roots:
        if not root.exists():
            continue
        for ext in ("*.parquet", "*.csv", "*.gpkg"):
            for p in root.rglob(ext):
                if p in seen:
                    continue
                n = norm(str(p))
                if needle in n or (kind == "score" and "akerscore" in n):
                    out.append(p)
                    seen.add(p)
                if len(out) >= 60:
                    return out
    return out

def load_metric(kind, target_ids, inventory):
    colfun = score_col if kind == "score" else drift_col
    best = None
    best_overlap = -1
    for p in metric_candidates(kind):
        try:
            d = read_table(p)
            mc = colfun(d.columns)
            if mc is None:
                inventory.append({"kind": kind, "file": str(p), "status": "NO_METRIC", "overlap": 0})
                continue
            ids = derive_field_id(d)
            overlap = int(ids.isin(target_ids).sum())
            inventory.append({
                "kind": kind, "file": str(p), "status": "OK",
                "metric_col": mc, "rows": len(d), "overlap": overlap,
            })
            if overlap > best_overlap:
                best_overlap = overlap
                best = (p, d, ids, mc)
        except Exception as e:
            inventory.append({
                "kind": kind, "file": str(p),
                "status": "ERROR_" + type(e).__name__, "overlap": 0,
            })
    if best is None:
        return None
    p, d, ids, mc = best
    x = pd.DataFrame({
        "field_id": ids,
        kind: pd.to_numeric(d[mc], errors="coerce"),
    })
    x = x[x.field_id != ""].drop_duplicates("field_id")
    return {"path": p, "column": mc, "data": x, "overlap": best_overlap}

def load_sjobo_geometry():
    sp = first_existing(SKIFTE_CANDIDATES)
    bp = first_existing(BLOCK_CANDIDATES)
    if sp is None or bp is None:
        raise FileNotFoundError("Hittar inte 2025 Skåne skifte/block-GPKG.")

    blocks = gpd.read_file(bp).to_crs(3006)
    bc = block_col(blocks.columns)
    rc = region_col(blocks.columns)
    if not bc or not rc:
        raise RuntimeError("Blockfilen saknar blockid eller region_kod.")

    sj = blocks[blocks[rc].astype(str).str.startswith(SJÖBO_CODE)].copy()
    sj_blocks = set(sj[bc].map(canon))

    f = gpd.read_file(sp).to_crs(3006)
    fbc = block_col(f.columns)
    fsc = skifte_col(f.columns)
    if not fbc or not fsc:
        raise RuntimeError("Skiftesfilen saknar blockid eller skiftesbeteckning.")

    f["__block"] = f[fbc].map(canon)
    f = f[f["__block"].isin(sj_blocks)].copy()
    f["field_id"] = f["__block"] + "|" + f[fsc].map(canon)
    f = f[~f.geometry.isna() & ~f.geometry.is_empty].copy()
    f["area_ha"] = f.geometry.area / 10000.0
    f = f[f.area_ha > 0.05].drop_duplicates("field_id").reset_index(drop=True)
    return f[["field_id", "area_ha", "geometry"]], sp, bp

def counts_for(n, pairs, dist, mask, radius):
    c = np.zeros(n, dtype=np.int32)
    use = mask & (dist <= radius)
    if use.any():
        pp = pairs[use]
        np.add.at(c, pp[:, 0], 1)
        np.add.at(c, pp[:, 1], 1)
    return c

def stats(c):
    return {
        "p_ge_1": float(np.mean(c >= 1)),
        "p_ge_3": float(np.mean(c >= 3)),
        "p_ge_5": float(np.mean(c >= 5)),
        "median": float(np.median(c)),
        "p90": float(np.quantile(c, 0.90)),
        "max": int(c.max(initial=0)),
    }

def pct(x):
    return f"{100.0 * float(x):.1f}%"

def pick(df, radius, area_tol=None, score_tol=None, drift_tol=None, model=None):
    q = df[np.isclose(df.radius_km, radius)].copy()
    if model is not None:
        q = q[q.model == model]
    if area_tol is not None:
        q = q[np.isclose(q.area_tol, area_tol)]
    if score_tol is not None:
        q = q[np.isclose(q.score_tol, score_tol)]
    if drift_tol is not None:
        q = q[np.isclose(q.drift_tol, drift_tol)]
    return q.iloc[0]

def stop_needs_input(reason, extra=None):
    OUT.mkdir(parents=True, exist_ok=True)
    obj = {"version": VERSION, "verdict": "NEEDS_INPUT", "reason": reason}
    if extra:
        obj.update(extra)
    (OUT / "verdict.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print("AKERSWAP_A_RESULT")
    print("VERDICT=NEEDS_INPUT")
    print("REASON=" + reason)
    print("OUT=" + str(OUT))
    sys.exit(3)

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("=" * 92)
    print("ÅkerSwap A - Sjöbo substitutions-feasibility")
    print("Version:", VERSION)
    print("=" * 92)

    fields, skifte_path, block_path = load_sjobo_geometry()
    n_raw = len(fields)
    ids = set(fields.field_id)
    print(f"Sjöbo geometri: {n_raw:,} skiften")
    print("Skifte:", skifte_path)
    print("Block :", block_path)

    inventory = []
    score = load_metric("score", ids, inventory)
    drift = load_metric("drift", ids, inventory)
    pd.DataFrame(inventory).to_csv(OUT / "source_discovery.csv", index=False, encoding="utf-8-sig")

    if score is None or drift is None:
        missing = []
        if score is None:
            missing.append("ÅkerScore")
        if drift is None:
            missing.append("ÅkerDrift")
        stop_needs_input("Saknar " + " + ".join(missing))

    print("ÅkerScore:", score["path"], "[" + score["column"] + "]")
    print("ÅkerDrift:", drift["path"], "[" + drift["column"] + "]")

    f = fields.merge(score["data"], on="field_id", how="left")
    f = f.merge(drift["data"], on="field_id", how="left")
    score_cov = float(f.score.notna().mean())
    drift_cov = float(f.drift.notna().mean())
    f = f[np.isfinite(f.score) & np.isfinite(f.drift) & np.isfinite(f.area_ha)].copy().reset_index(drop=True)
    n = len(f)

    print(f"ÅkerScore coverage: {100*score_cov:.1f}%")
    print(f"ÅkerDrift coverage: {100*drift_cov:.1f}%")
    print(f"Eligible: {n:,}/{n_raw:,}")

    if n < 500 or n < 0.50 * n_raw:
        stop_needs_input("För låg gemensam ÅkerScore/ÅkerDrift coverage", {
            "n_raw": n_raw, "n_eligible": n,
            "score_coverage": score_cov, "drift_coverage": drift_cov,
        })

    cent = f.geometry.centroid
    xy = np.column_stack([cent.x.to_numpy(), cent.y.to_numpy()])
    pairs = cKDTree(xy).query_pairs(max(RADII_M), output_type="ndarray")
    if pairs.size == 0:
        pairs = np.empty((0, 2), dtype=np.int64)

    dist = np.sqrt(np.sum((xy[pairs[:, 0]] - xy[pairs[:, 1]]) ** 2, axis=1)) if len(pairs) else np.array([])
    area = f.area_ha.to_numpy(float)
    scorev = f.score.to_numpy(float)
    driftv = f.drift.to_numpy(float)

    ai = area[pairs[:, 0]]
    aj = area[pairs[:, 1]]
    area_rel = np.abs(ai - aj) / np.maximum((ai + aj) / 2.0, 1e-9)
    score_diff = np.abs(scorev[pairs[:, 0]] - scorev[pairs[:, 1]])
    drift_diff = np.abs(driftv[pairs[:, 0]] - driftv[pairs[:, 1]])

    print(f"Pairs <=10 km: {len(pairs):,}")

    ablation = []
    models = {
        "GEO": np.ones(len(pairs), dtype=bool),
        "AREA20": area_rel <= 0.20,
        "AREA20_SCORE10": (area_rel <= 0.20) & (score_diff <= 10.0),
        "FULL_CORE": (area_rel <= 0.20) & (score_diff <= 10.0) & (drift_diff <= 10.0),
    }
    for model, mask in models.items():
        for radius in RADII_M:
            ablation.append({
                "model": model, "radius_km": radius / 1000.0,
                **stats(counts_for(n, pairs, dist, mask, radius)),
            })
    ab = pd.DataFrame(ablation)
    ab.to_csv(OUT / "ablation_by_radius.csv", index=False, encoding="utf-8-sig")

    sweep = []
    for at in AREA_TOLS:
        for st in SCORE_TOLS:
            for dt in DRIFT_TOLS:
                mask = (area_rel <= at) & (score_diff <= st) & (drift_diff <= dt)
                for radius in RADII_M:
                    sweep.append({
                        "area_tol": at, "score_tol": st, "drift_tol": dt,
                        "radius_km": radius / 1000.0,
                        **stats(counts_for(n, pairs, dist, mask, radius)),
                    })
    sw = pd.DataFrame(sweep)
    sw.to_csv(OUT / "parameter_sweep.csv", index=False, encoding="utf-8-sig")

    core_mask = (area_rel <= CORE[0]) & (score_diff <= CORE[1]) & (drift_diff <= CORE[2])

    nearest = np.full(n, np.inf)
    if core_mask.any():
        pp = pairs[core_mask]
        dd = dist[core_mask]
        np.minimum.at(nearest, pp[:, 0], dd)
        np.minimum.at(nearest, pp[:, 1], dd)
    nearest[np.isinf(nearest)] = np.nan
    f["nearest_core_equiv_km"] = nearest / 1000.0

    core5_idx = np.where(core_mask & (dist <= 5000.0))[0]
    nonadj_mask = np.zeros(len(pairs), dtype=bool)
    if len(core5_idx):
        print(f"Boundary robustness: {len(core5_idx):,} core-par <=5 km")
        pp5 = pairs[core5_idx]
        geoms = f.geometry.to_numpy()
        try:
            bd = np.asarray(shapely.distance(geoms[pp5[:, 0]], geoms[pp5[:, 1]]), dtype=float)
        except Exception:
            bd = np.array([geoms[i].distance(geoms[j]) for i, j in pp5], dtype=float)
        keep = core5_idx[np.isfinite(bd) & (bd > ADJACENCY_M)]
        nonadj_mask[keep] = True

    robustness = []
    for model, mask in (
        ("CORE_ALL", core_mask),
        ("CORE_NONADJ_GT_10M", nonadj_mask),
    ):
        for radius in (2000.0, 5000.0):
            robustness.append({
                "model": model, "radius_km": radius / 1000.0,
                **stats(counts_for(n, pairs, dist, mask, radius)),
            })
    rb = pd.DataFrame(robustness)
    rb.to_csv(OUT / "adjacency_robustness.csv", index=False, encoding="utf-8-sig")

    core2 = pick(sw, 2.0, *CORE)
    core5 = pick(sw, 5.0, *CORE)
    strict2 = pick(sw, 2.0, *STRICT)
    nonadj2 = pick(rb, 2.0, model="CORE_NONADJ_GT_10M")
    nonadj5 = pick(rb, 5.0, model="CORE_NONADJ_GT_10M")

    if core2.p_ge_1 >= 0.50 and core5.p_ge_5 >= 0.25 and nonadj2.p_ge_1 >= 0.35:
        verdict = "PASS"
    elif core5.p_ge_1 >= 0.50 and nonadj5.p_ge_1 >= 0.35:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    nv = f.nearest_core_equiv_km.dropna()
    nearest_median = float(nv.median()) if len(nv) else None

    f.drop(columns="geometry").to_parquet(OUT / "sjobo_fields_core.parquet", index=False)
    try:
        f[["field_id", "area_ha", "score", "drift", "nearest_core_equiv_km", "geometry"]].to_file(
            OUT / "sjobo_fields_core.gpkg", driver="GPKG"
        )
    except Exception as e:
        print("VARNING GPKG:", e)

    result = {
        "version": VERSION,
        "verdict": verdict,
        "municipality": "Sjöbo",
        "n_raw_fields": n_raw,
        "n_eligible_fields": n,
        "score_source": str(score["path"]),
        "score_column": score["column"],
        "drift_source": str(drift["path"]),
        "drift_column": drift["column"],
        "core": {"area_tol": CORE[0], "score_tol": CORE[1], "drift_tol": CORE[2]},
        "core_2km_ge1": float(core2.p_ge_1),
        "core_2km_ge5": float(core2.p_ge_5),
        "core_5km_ge1": float(core5.p_ge_1),
        "core_5km_ge5": float(core5.p_ge_5),
        "strict_2km_ge1": float(strict2.p_ge_1),
        "nonadj_core_2km_ge1": float(nonadj2.p_ge_1),
        "nonadj_core_5km_ge1": float(nonadj5.p_ge_1),
        "nearest_core_median_km": nearest_median,
        "note": "PASS/MARGINAL/FAIL thresholds are explicit v0a project go/no-go heuristics.",
    }
    (OUT / "verdict.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# ÅkerSwap STOPPUNKT A - Sjöbo substitutions-feasibility",
        "",
        "Version: " + VERSION,
        "Verdict: " + verdict,
        "",
        "Test: finns många geografiskt nära och ungefär likvärdiga substitut utan att känna faktisk brukare?",
        "",
        f"Fields: {n:,}/{n_raw:,}",
        "Core: area <=20%, ÅkerScore diff <=10, ÅkerDrift diff <=10.",
        "",
        f"Core 2 km >=1: {pct(core2.p_ge_1)}",
        f"Core 2 km >=5: {pct(core2.p_ge_5)}",
        f"Core 5 km >=1: {pct(core5.p_ge_1)}",
        f"Core 5 km >=5: {pct(core5.p_ge_5)}",
        f"Strict 2 km >=1: {pct(strict2.p_ge_1)}",
        f"Non-adj core 2 km >=1: {pct(nonadj2.p_ge_1)}",
        f"Non-adj core 5 km >=1: {pct(nonadj5.p_ge_1)}",
        "",
        "Ablation: GEO -> AREA20 -> AREA20+SCORE10 -> FULL_CORE.",
        "Robusthet: direkt angränsande par <=10 m exkluderas i non-adj-testet.",
        "",
        "Beslut:",
        (
            "Gå vidare till B1+B2+B3 som en sammanhållen falsifieringssprint: single hub -> multi-hub -> sparse-swap. "
            "Ingen webb och ingen riktig pilot."
            if verdict in ("PASS", "MARGINAL")
            else
            "STOPP. Kör inte B-sprinten innan hypotes/data har omformulerats."
        ),
    ]
    (OUT / "STOPPUNKT_A.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("")
    print("=" * 92)
    print("AKERSWAP_A_RESULT")
    print("VERDICT=" + verdict)
    print(f"FIELDS={n:,}/{n_raw:,}")
    print("CORE_2KM_GE1=" + pct(core2.p_ge_1))
    print("CORE_2KM_GE5=" + pct(core2.p_ge_5))
    print("CORE_5KM_GE1=" + pct(core5.p_ge_1))
    print("CORE_5KM_GE5=" + pct(core5.p_ge_5))
    print("STRICT_2KM_GE1=" + pct(strict2.p_ge_1))
    print("NONADJ_CORE_2KM_GE1=" + pct(nonadj2.p_ge_1))
    print("NONADJ_CORE_5KM_GE1=" + pct(nonadj5.p_ge_1))
    if nearest_median is not None:
        print(f"NEAREST_CORE_MEDIAN_KM={nearest_median:.3f}")
    print("OUT=" + str(OUT))
    print("=" * 92)

if __name__ == "__main__":
    main()
