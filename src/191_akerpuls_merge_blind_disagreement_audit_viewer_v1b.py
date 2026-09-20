#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build blind 100-pair merge-boundary audit across frozen M0/M1 extremes.

Predeclared V1B sample among the exact 22,358 M0-assessable pairs:
  HH: M0 upper decile, M1 p_samecrop upper quartile
  HL: M0 upper decile, M1 p_samecrop lower quartile
  LH: M0 lower decile, M1 p_samecrop upper quartile
  LL: M0 lower decile, M1 p_samecrop lower quartile
Exactly 25 deterministic hash-sampled pairs per stratum.

V1 used decile/decile corners and stopped before rendering because HL had only
14 pairs. V1B preserves M0 extreme deciles but widens only the pre-label M1
contrast to global upper/lower quartiles; no human labels have been opened.

The browser shows only four frozen 2026 Sentinel-2 natural-colour panels and the
old shared 2025 boundary. Scores, strata, pair IDs and M0 status remain hidden in
a separate blind key until labels are exported and frozen.

No fusion, sign selection, threshold tuning, automatic merge or geometry mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"

M2_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_freeze_v1\AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_FREEZE_V1.json")
EXPECTED_M2_FREEZE_SHA256 = "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859"
M2_JOIN = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_v1\M2_M0_M1_DIAGNOSTIC_JOIN.parquet")
EXPECTED_M2_JOIN_SHA256 = "e4cfed6a9e2488a91eeaeea5535492d040ff972287b62bdb07fad702fba7137d"

M0_FREEZE = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json")
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
M0_GPKG = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1\m0_satellite_merge_boundaries.gpkg")

D1_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1")
VRT_INDEX = D1_DIR / "d1s3j_vrt_outputs.csv"
EXPECTED_VRT_INDEX_SHA256 = "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"

DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1")
STATUS = "PASS_TO_BLIND_MERGE_DISAGREEMENT_AUDIT_V1B"
EXPECTED_PAIRS = 27146
EXPECTED_ASSESSABLE = 22358
SAMPLE_PER_STRATUM = 25
EXPECTED_SAMPLE = 100
HIGH_Q = 0.90
LOW_Q = 0.10
SAMPLE_SALT = "akerpuls-merge-disagreement-audit-sample-v1b|2026-09-20|54a567c2|m0decile-m1quartile"
BLIND_ORDER_SALT = "akerpuls-merge-disagreement-audit-order-v1b|2026-09-20|54a567c2|m0decile-m1quartile"
BUFFER_M = 100.0
PANEL_PX = 380
HEADER_PX = 28
TITLE_PX = 44
EXPECTED_EPSG = 32633
EXPECTED_BANDS = ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "VALID", "NDVI", "LSWI", "SOURCE_DATE_INDEX"]
SNAPSHOTS = [
    ("S2_2026_APRIL", "8/9 april"),
    ("S2_2026_MAY", "25 maj"),
    ("S2_2026_JUNE", "26/27 juni"),
    ("S2_2026_JULY", "9 juli"),
]
LABELS = ["TYDLIG_MERGE", "MÖJLIG_MERGE", "TVEKSAM", "BEHÅLL_GRÄNS", "EJ_BEDÖMBAR"]
PREDECLARED_ANALYSIS = {
    "strict_positive": ["TYDLIG_MERGE"],
    "broad_positive": ["TYDLIG_MERGE", "MÖJLIG_MERGE"],
    "ambiguous": ["TVEKSAM"],
    "negative": ["BEHÅLL_GRÄNS"],
    "excluded": ["EJ_BEDÖMBAR"],
    "primary_contrasts": [
        "HH_vs_HL: M1 high vs low conditional on high M0",
        "LH_vs_LL: M1 high vs low conditional on low M0",
        "HH_vs_LH: M0 high vs low conditional on high M1",
        "HL_vs_LL: M0 high vs low conditional on low M1",
    ],
    "no_fusion_weight_or_threshold_selected_before_labels_frozen": True,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(x: str) -> str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def verify_lineage():
    if not M2_FREEZE.is_file() or sha256_file(M2_FREEZE) != EXPECTED_M2_FREEZE_SHA256:
        raise RuntimeError("M2 freeze missing or SHA changed")
    m2f = read_json(M2_FREEZE)
    if m2f.get("status") != "FROZEN_AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_V1":
        raise RuntimeError("Unexpected M2 freeze status")
    if not M2_JOIN.is_file() or sha256_file(M2_JOIN) != EXPECTED_M2_JOIN_SHA256:
        raise RuntimeError("Frozen M2 joined Parquet changed")

    if not M0_FREEZE.is_file() or sha256_file(M0_FREEZE) != EXPECTED_M0_FREEZE_SHA256:
        raise RuntimeError("M0 freeze missing or SHA changed")
    m0f = read_json(M0_FREEZE)
    gpkg_sha = m0f.get("source_hashes", {}).get("source_boundaries_gpkg_sha256")
    if not gpkg_sha or not M0_GPKG.is_file() or sha256_file(M0_GPKG) != gpkg_sha:
        raise RuntimeError("Frozen M0 shared-boundary GPKG changed")

    if not VRT_INDEX.is_file() or sha256_file(VRT_INDEX) != EXPECTED_VRT_INDEX_SHA256:
        raise RuntimeError("Frozen D1 VRT index changed")
    rows = pd.read_csv(VRT_INDEX, encoding="utf-8-sig")
    if set(rows["snapshot"].astype(str)) != {x[0] for x in SNAPSHOTS}:
        raise RuntimeError("Frozen VRT snapshot set changed")
    vrt_paths, vrt_hashes = {}, {}
    for snap, _ in SNAPSHOTS:
        r = rows.loc[rows["snapshot"].astype(str) == snap]
        if len(r) != 1:
            raise RuntimeError(f"Expected one VRT row for {snap}")
        p = Path(str(r.iloc[0]["path"]))
        expected = str(r.iloc[0]["sha256"])
        if not p.is_file() or sha256_file(p) != expected:
            raise RuntimeError(f"Frozen VRT changed for {snap}")
        vrt_paths[snap] = p
        vrt_hashes[snap] = expected
    return gpkg_sha, vrt_paths, vrt_hashes


def sample_hash(pair_key: str, stratum: str) -> str:
    return sha256_text(f"{SAMPLE_SALT}|{stratum}|{pair_key}")


def blind_hash(pair_key: str) -> str:
    return sha256_text(f"{BLIND_ORDER_SALT}|{pair_key}")


def _shift_bool(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(a, dtype=bool)
    ys = slice(max(0, dy), a.shape[0] + min(0, dy))
    xs = slice(max(0, dx), a.shape[1] + min(0, dx))
    sy = slice(max(0, -dy), a.shape[0] - max(0, dy))
    sx = slice(max(0, -dx), a.shape[1] - max(0, dx))
    out[ys, xs] = a[sy, sx]
    return out


def halo(mask: np.ndarray) -> np.ndarray:
    h = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            h |= _shift_bool(mask, dy, dx)
    return h


def joint_rgb_stretch(rgb_arrays, valid_arrays):
    lows, highs = [], []
    for b in range(3):
        vals = []
        for rgb, valid in zip(rgb_arrays, valid_arrays):
            x = np.asarray(rgb[b], dtype=np.float32)
            m = valid & np.isfinite(x)
            if m.any():
                vals.append(x[m])
        if not vals:
            lows.append(0.0); highs.append(1.0); continue
        v = np.concatenate(vals)
        lo, hi = np.percentile(v, [2.0, 98.0])
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo + 1e-9:
            lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
        if hi <= lo + 1e-9:
            lo, hi = 0.0, 1.0
        lows.append(float(lo)); highs.append(float(hi))
    out = []
    for rgb in rgb_arrays:
        img = np.empty((rgb.shape[1], rgb.shape[2], 3), dtype=np.uint8)
        for b in range(3):
            x = np.clip((rgb[b] - lows[b]) / (highs[b] - lows[b]), 0.0, 1.0)
            x = np.power(x, 0.90)
            img[..., b] = np.round(255.0 * x).astype(np.uint8)
        out.append(img)
    return out


def square_bounds(bounds, buffer_m=BUFFER_M):
    minx, miny, maxx, maxy = map(float, bounds)
    cx, cy = 0.5 * (minx + maxx), 0.5 * (miny + maxy)
    side = max(maxx - minx, maxy - miny) + 2 * float(buffer_m)
    half = 0.5 * side
    return cx - half, cy - half, cx + half, cy + half


def render_pair(shared_line, vrt_paths, dest: Path, blind_index: int):
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import from_bounds
    from PIL import Image, ImageDraw

    bounds = square_bounds(shared_line.bounds)
    rgbs, valids, validity = [], [], {}
    window = None
    line_mask = None
    grid0 = None
    for snap, _ in SNAPSHOTS:
        with rasterio.open(vrt_paths[snap]) as ds:
            desc = [str(x or "") for x in ds.descriptions]
            if desc != EXPECTED_BANDS:
                raise RuntimeError(f"Unexpected VRT bands for {snap}: {desc}")
            if ds.crs is None or ds.crs.to_epsg() != EXPECTED_EPSG:
                raise RuntimeError(f"Unexpected VRT CRS for {snap}: {ds.crs}")
            grid = (ds.width, ds.height, tuple(ds.transform))
            if grid0 is None:
                grid0 = grid
                w = from_bounds(*bounds, transform=ds.transform).round_offsets().round_lengths()
                full = rasterio.windows.Window(0, 0, ds.width, ds.height)
                window = w.intersection(full)
                tr = ds.window_transform(window)
                shape = (int(window.height), int(window.width))
                line_mask = rasterize([(shared_line, 1)], out_shape=shape, transform=tr, fill=0, all_touched=True, dtype="uint8").astype(bool)
                if not line_mask.any():
                    raise RuntimeError("Shared 2025 boundary failed to rasterize")
            elif grid != grid0:
                raise RuntimeError("Frozen VRT grids differ")
            band = {name: i + 1 for i, name in enumerate(desc)}
            rgb = np.stack([
                ds.read(band["B04"], window=window),
                ds.read(band["B03"], window=window),
                ds.read(band["B02"], window=window),
            ]).astype(np.float32, copy=False)
            valid = ds.read(band["VALID"], window=window) > 0.5
            rgbs.append(rgb); valids.append(valid)
            validity[snap] = float(valid.mean())

    imgs = joint_rgb_stretch(rgbs, valids)
    line_halo = halo(line_mask)
    panels = []
    for (snap, label), img0, valid in zip(SNAPSHOTS, imgs, valids):
        img = img0.copy()
        bad = ~valid
        if bad.any():
            tint = np.array([255, 40, 80], dtype=np.float32)
            img[bad] = np.clip(0.35 * img[bad].astype(np.float32) + 0.65 * tint, 0, 255).astype(np.uint8)
        img[line_halo & ~line_mask] = np.array([0, 0, 0], dtype=np.uint8)
        img[line_mask] = np.array([0, 255, 255], dtype=np.uint8)
        p = Image.fromarray(img, mode="RGB").resize((PANEL_PX, PANEL_PX), resample=Image.Resampling.NEAREST)
        c = Image.new("RGB", (PANEL_PX, PANEL_PX + HEADER_PX), "white")
        c.paste(p, (0, HEADER_PX))
        ImageDraw.Draw(c).text((6, 6), f"{label}   VALID={100*validity[snap]:.1f}%", fill="black")
        panels.append(c)

    sheet = Image.new("RGB", (PANEL_PX * 4, PANEL_PX + HEADER_PX + TITLE_PX), "white")
    ImageDraw.Draw(sheet).text(
        (8, 10),
        f"ÅkerPuls blind merge-audit #{blind_index:03d} | cyan = gemensam officiell 2025-gräns | magenta = ej VALID",
        fill="black",
    )
    for i, p in enumerate(panels):
        sheet.paste(p, (PANEL_PX * i, TITLE_PX))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".partial.jpg")
    sheet.save(tmp, format="JPEG", quality=92, subsampling=0, optimize=True)
    tmp.replace(dest)
    return validity


def build_html(items, key_sha: str) -> str:
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    labs = json.dumps(LABELS, ensure_ascii=False)
    template = r'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – blind merge-audit</title><style>
:root{font-family:Arial,sans-serif;color:#171717;background:#f5f5f5}body{margin:0}.top{position:sticky;top:0;z-index:3;background:#fff;border-bottom:1px solid #ccc;padding:10px 14px}.main{max-width:1600px;margin:12px auto;padding:0 12px 30px}.card{background:#fff;border:1px solid #ccc;border-radius:7px;padding:10px}.auditimg{display:block;width:100%;height:auto;background:#ddd}.labels{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.labels button,.nav button,#exportBtn{padding:9px 12px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}.labels button.sel{outline:3px solid #111;font-weight:bold}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.note{width:100%;min-height:55px;box-sizing:border-box}.muted{color:#555;font-size:13px}.warn{font-weight:bold}.progress{font-variant-numeric:tabular-nums}</style></head><body>
<div class="top"><div class="row"><b>ÅkerPuls – blind merge-audit</b><span id="pos" class="progress"></span><span id="done" class="progress"></span></div>
<div class="muted">Cyan = gemensam officiell 2025-gräns. Bedöm om den bör tas bort i preliminär 2026-geometri. Scores, strata, fält-ID och M0-status är dolda.</div></div>
<div class="main"><div class="card"><img id="img" class="auditimg"><p><b>Bedömning:</b> Tyder 2026-bilderna på att de två 2025-skiftena nu fungerar som ett och samma skifte så att den cyan gränsen bör tas bort?</p>
<div class="labels" id="labels"></div><textarea id="note" class="note" placeholder="Frivillig kort kommentar"></textarea>
<div class="row nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button><button id="exportBtn">Exportera audit CSV</button><span class="muted">1–5 = etikett, ←/→ = navigera.</span></div>
<p class="muted warn">Viktigt: samma gröda/färg på båda sidor räcker inte i sig för merge. Leta efter evidens att den gamla brukningsgränsen faktiskt inte längre fungerar som separat 2026-gräns över säsongen.</p>
<p class="muted warn">Öppna inte BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv före export och freeze av etiketterna.</p></div></div>
<script>
const ITEMS=__ITEMS__, LABELS=__LABELS__, FREEZE='__FREEZE__', KEYSHA='__KEYSHA__';
const STORE='akerpuls_merge_blind_audit_v1_'+FREEZE.slice(0,12)+'_'+KEYSHA.slice(0,12); let state=JSON.parse(localStorage.getItem(STORE)||'{}'); let idx=0;
function save(){localStorage.setItem(STORE,JSON.stringify(state));} function cur(){return ITEMS[idx];}
function render(){const it=cur(),r=state[it.blind_index]||{};document.getElementById('img').src=it.image;document.getElementById('pos').textContent='Par '+(idx+1)+'/'+ITEMS.length+' · blind #'+String(it.blind_index).padStart(3,'0');document.getElementById('note').value=r.note||'';const box=document.getElementById('labels');box.innerHTML='';LABELS.forEach(function(lab){const b=document.createElement('button');b.textContent=lab;if(r.merge_label===lab)b.classList.add('sel');b.onclick=function(){const rr=state[it.blind_index]||{};rr.merge_label=lab;rr.note=document.getElementById('note').value;state[it.blind_index]=rr;save();render();};box.appendChild(b);});const n=ITEMS.filter(function(x){return state[x.blind_index]&&state[x.blind_index].merge_label;}).length;document.getElementById('done').textContent='Bedömda '+n+'/'+ITEMS.length;}
document.getElementById('note').addEventListener('input',function(e){const it=cur(),r=state[it.blind_index]||{};r.note=e.target.value;state[it.blind_index]=r;save();});document.getElementById('prev').onclick=function(){idx=Math.max(0,idx-1);render();};document.getElementById('next').onclick=function(){idx=Math.min(ITEMS.length-1,idx+1);render();};
document.addEventListener('keydown',function(e){if(document.activeElement===document.getElementById('note'))return;if(e.key>='1'&&e.key<='5'){const it=cur(),r=state[it.blind_index]||{};r.merge_label=LABELS[Number(e.key)-1];state[it.blind_index]=r;save();render();return;}if(e.key==='ArrowRight'){idx=Math.min(ITEMS.length-1,idx+1);render();}else if(e.key==='ArrowLeft'){idx=Math.max(0,idx-1);render();}});
function q(s){return '"'+String(s||'').replaceAll('"','""')+'"';}
document.getElementById('exportBtn').onclick=function(){const missing=ITEMS.filter(function(x){return !(state[x.blind_index]&&state[x.blind_index].merge_label);});if(missing.length&&!confirm(String(missing.length)+' par saknar etikett. Exportera ändå?'))return;const rows=[['m2_diagnostic_freeze_sha256','blind_key_sha256','blind_index','merge_label','note']];ITEMS.forEach(function(it){const r=state[it.blind_index]||{};rows.push([FREEZE,KEYSHA,it.blind_index,r.merge_label||'',r.note||'']);});const csv='\ufeff'+rows.map(function(r){return r.map(q).join(',');}).join('\r\n')+'\r\n';const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='merge_disagreement_audit_labels.csv';a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);};render();
</script></body></html>'''
    return template.replace("__ITEMS__", payload).replace("__LABELS__", labs).replace("__FREEZE__", EXPECTED_M2_FREEZE_SHA256).replace("__KEYSHA__", key_sha)


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    head = git_guard()
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    gpkg_sha, vrt_paths, vrt_hashes = verify_lineage()
    print("AKERPULS MERGE BLIND DISAGREEMENT AUDIT VIEWER V1B")
    print(f"GIT_HEAD={head}")
    print(f"M2_DIAGNOSTIC_FREEZE_SHA256={EXPECTED_M2_FREEZE_SHA256}")
    print("PROGRESS=BUILD_PREDECLARED_V1B_4X25_M0_DECILE_M1_QUARTILE_SAMPLE")

    cols = ["pair_key", "field_a", "field_b", "m0_status", "satellite_merge_score", "satellite_score_percentile", "p_samecrop", "top1_same", "top1_class_a", "top1_class_b"]
    d = pd.read_parquet(M2_JOIN, columns=cols)
    if len(d) != EXPECTED_PAIRS or d["pair_key"].nunique() != EXPECTED_PAIRS:
        raise RuntimeError("M2 joined population changed")
    a = d.loc[d["m0_status"].isin(["MERGE_CANDIDATE", "KEEP_BOUNDARY"])].copy()
    if len(a) != EXPECTED_ASSESSABLE:
        raise RuntimeError("Assessable population changed")
    a["m1_pct"] = a["p_samecrop"].rank(method="average", pct=True)
    if a["satellite_score_percentile"].isna().any():
        raise RuntimeError("Assessable M0 percentile contains null")

    strata_masks = {
        "HH": (a["satellite_score_percentile"] > M0_HIGH_Q) & (a["m1_pct"] > M1_HIGH_Q),
        "HL": (a["satellite_score_percentile"] > M0_HIGH_Q) & (a["m1_pct"] <= M1_LOW_Q),
        "LH": (a["satellite_score_percentile"] <= M0_LOW_Q) & (a["m1_pct"] > M1_HIGH_Q),
        "LL": (a["satellite_score_percentile"] <= M0_LOW_Q) & (a["m1_pct"] <= M1_LOW_Q),
    }
    stratum_counts = {k: int(v.sum()) for k, v in strata_masks.items()}
    print("STRATUM_COUNTS=" + " | ".join(f"{k}:{v}" for k, v in stratum_counts.items()))
    if any(v < SAMPLE_PER_STRATUM for v in stratum_counts.values()):
        raise RuntimeError(f"One or more strata have <{SAMPLE_PER_STRATUM} pairs: {stratum_counts}")

    sampled = []
    for stratum, mask in strata_masks.items():
        g = a.loc[mask].copy()
        g["stratum"] = stratum
        g["sample_hash"] = [sample_hash(pk, stratum) for pk in g["pair_key"].astype(str)]
        sampled.append(g.sort_values(["sample_hash", "pair_key"], kind="mergesort").head(SAMPLE_PER_STRATUM))
    sample = pd.concat(sampled, ignore_index=True)
    if len(sample) != EXPECTED_SAMPLE or sample["pair_key"].duplicated().any():
        raise RuntimeError("Blind audit sample is not exactly 100 unique pairs")
    sample["blind_hash"] = [blind_hash(pk) for pk in sample["pair_key"].astype(str)]
    sample = sample.sort_values(["blind_hash", "pair_key"], kind="mergesort").reset_index(drop=True)
    sample["blind_index"] = np.arange(1, EXPECTED_SAMPLE + 1, dtype=int)

    print("PROGRESS=LOAD_FROZEN_SHARED_BOUNDARY_GEOMETRY")
    g = gpd.read_file(M0_GPKG)
    if len(g) != EXPECTED_PAIRS:
        raise RuntimeError("M0 boundary GPKG row count changed")
    if g.crs is None or g.crs.to_epsg() != EXPECTED_EPSG:
        g = g.to_crs(EXPECTED_EPSG)
    g["pair_key"] = g["field_a"].astype(str) + "||" + g["field_b"].astype(str)
    if g["pair_key"].duplicated().any():
        raise RuntimeError("M0 boundary GPKG pair keys not unique")
    geom = g.set_index("pair_key").geometry
    if not set(sample["pair_key"]).issubset(set(geom.index)):
        raise RuntimeError("Audit sample pair missing shared-boundary geometry")

    out.mkdir(parents=True, exist_ok=False)
    imgdir = out / "images"; imgdir.mkdir()

    key_fields = ["blind_index", "pair_key", "stratum", "sample_hash", "blind_hash", "m0_status", "satellite_merge_score", "satellite_score_percentile", "p_samecrop", "m1_pct", "top1_same", "top1_class_a", "top1_class_b"]
    key_path = out / "BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
    sample[key_fields].to_csv(key_path, index=False, encoding="utf-8-sig")
    key_sha = sha256_file(key_path)

    items, image_hashes, validity_rows = [], {}, []
    print("PROGRESS=RENDER_100_X_4_BLIND_PAIR_SHEETS")
    for i, r in enumerate(sample.itertuples(index=False), 1):
        bi = int(r.blind_index)
        name = f"audit_{bi:03d}.jpg"
        dest = imgdir / name
        valid = render_pair(geom.loc[str(r.pair_key)], vrt_paths, dest, bi)
        image_hashes[name] = sha256_file(dest)
        validity_rows.append({"blind_index": bi, **valid})
        items.append({"blind_index": bi, "image": f"images/{name}"})
        if i == 1 or i % 10 == 0 or i == EXPECTED_SAMPLE:
            print(f"AUDIT_RENDERED={i}/{EXPECTED_SAMPLE}")

    html = out / "index.html"
    html.write_text(build_html(items, key_sha), encoding="utf-8")
    validity = out / "blind_pair_validity.json"; write_json(validity, validity_rows)

    sample_population_sha = sha256_text("\n".join(sorted(sample["pair_key"].astype(str))) + "\n")
    manifest = {
        "schema_version": "akerpuls-merge-blind-disagreement-audit-viewer-v1b",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_m2_diagnostic_freeze_sha256": EXPECTED_M2_FREEZE_SHA256,
        "parent_m2_join_sha256": EXPECTED_M2_JOIN_SHA256,
        "m0_freeze_sha256": EXPECTED_M0_FREEZE_SHA256,
        "m0_shared_boundary_gpkg_sha256": gpkg_sha,
        "vrt_index_sha256": EXPECTED_VRT_INDEX_SHA256,
        "vrt_hashes": vrt_hashes,
        "assessable_population": EXPECTED_ASSESSABLE,
        "sample": {
            "rows": EXPECTED_SAMPLE,
            "design_revision": "V1B_AFTER_PRELABEL_V1_FEASIBILITY_STOP_HL14",
            "v1_failed_prelabel_stratum_counts": {"HH": 433, "HL": 14, "LH": 36, "LL": 181},
            "m0_tail_fraction": 0.10,
            "m1_tail_fraction": 0.25,
            "per_stratum": SAMPLE_PER_STRATUM,
            "stratum_population_counts": stratum_counts,
            "strata": {
                "HH": "M0 percentile > 0.90 AND M1 percentile > 0.75",
                "HL": "M0 percentile > 0.90 AND M1 percentile <= 0.25",
                "LH": "M0 percentile <= 0.10 AND M1 percentile > 0.75",
                "LL": "M0 percentile <= 0.10 AND M1 percentile <= 0.25",
            },
            "sample_method": "LOWEST_SHA256_25_PER_STRATUM_M0_DECILE_M1_QUARTILE_WITH_FROZEN_SALT",
            "sample_salt": SAMPLE_SALT,
            "blind_order_salt": BLIND_ORDER_SALT,
            "sample_population_sha256": sample_population_sha,
        },
        "blind_key_sha256": key_sha,
        "predeclared_analysis": PREDECLARED_ANALYSIS,
        "labels": LABELS,
        "rendering": {
            "shared_2025_boundary": "CYAN_WITH_BLACK_HALO",
            "invalid_pixels": "MAGENTA_TINT",
            "buffer_m": BUFFER_M,
            "joint_p02_p98_rgb_stretch_across_four_dates": True,
            "gamma": 0.90,
            "same_crop_alone_is_not_merge_evidence": True,
        },
        "blindness": {
            "scores_visible": False,
            "stratum_visible": False,
            "pair_id_visible": False,
            "m0_status_visible": False,
            "blind_key_must_remain_closed_until_labels_exported_and_frozen": True,
        },
        "guards": {
            "fusion_executed": False,
            "fusion_score_created": False,
            "sign_selected": False,
            "human_labels_used_for_sampling": False,
            "thresholds_tuned": False,
            "automatic_merge": False,
            "geometry_mutated": False,
            "review_only": True,
        },
        "html_sha256": sha256_file(html),
        "validity_sha256": sha256_file(validity),
        "image_hashes": image_hashes,
        "next": "HUMAN_REVIEW_100_THEN_FREEZE_LABELS_BEFORE_OPENING_BLIND_KEY",
    }
    manifest_path = out / "MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_MANIFEST_V1.json"; write_json(manifest_path, manifest)

    print(f"STATUS={STATUS}")\n    print("DESIGN=M0_TOP_BOTTOM_10_PERCENT__M1_TOP_BOTTOM_25_PERCENT")
    print(f"ASSESSABLE_POPULATION={EXPECTED_ASSESSABLE} AUDIT_SAMPLE={EXPECTED_SAMPLE} PER_STRATUM={SAMPLE_PER_STRATUM}")
    print("STRATUM_COUNTS=" + " | ".join(f"{k}:{v}" for k, v in stratum_counts.items()))
    print(f"SAMPLE_POPULATION_SHA256={sample_population_sha}")
    print(f"BLIND_KEY_SHA256={key_sha}")
    print("SCORES_VISIBLE=FALSE STRATUM_VISIBLE=FALSE PAIR_ID_VISIBLE=FALSE M0_STATUS_VISIBLE=FALSE")
    print("FUSION_EXECUTED=FALSE SIGN_SELECTED=FALSE THRESHOLDS_TUNED=FALSE AUTOMATIC_MERGE=FALSE GEOMETRY_MUTATED=FALSE")
    print("DO_NOT_OPEN_BLIND_KEY_BEFORE_LABEL_FREEZE=TRUE")
    print(f"OUTPUT={html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
