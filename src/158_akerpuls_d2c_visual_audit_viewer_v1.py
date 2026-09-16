#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the post-freeze blind 100-field D2C visual audit viewer.

This stage is review-only and zero-network. It consumes the exact frozen D2C
100-field audit sample plus the exact frozen D1-S3j Sentinel-2 snapshot VRTs.
It renders four same-extent natural-colour panels per field (April/May/June/July),
with official 2025 parent boundary and invalid/cloud pixels visibly marked.

No model is executed, no score/threshold is changed, no split line is generated,
and no frozen D2C artifact is modified. P95/P90-only strata and fusion signals are
kept out of the HTML to preserve blind review; they are retained only in a
separate reveal key that must not be opened before labels are frozen/exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_D2C = Path(r"C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1")
DEFAULT_D1 = Path(r"C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1")
DEFAULT_DERIVED = Path(r"C:\AkerSyncRaw\akerpuls_full_skane_s3_v1")
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_D2C_STATUS = "FROZEN_FULL_SKANE_QA_RANKING_V1"
EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_D1_STATUS = "PASS_TO_FULL_SKANE_D1_RASTER_QA"
EXPECTED_D1_SNAPSHOT_INDEX_SHA256 = "a3a26d1f454a8c0d65e326a913b0d10d91c54d4ba9886315ec5d5dd1e35cafff"
EXPECTED_D1_VRT_INDEX_SHA256 = "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"
EXPECTED_AUDIT_ROWS = 100
EXPECTED_P95_AUDIT = 50
EXPECTED_P90_ONLY_AUDIT = 50
EXPECTED_EPSG = 32633
EXPECTED_BANDS = ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "VALID", "NDVI", "LSWI", "SOURCE_DATE_INDEX"]
SNAPSHOTS = [
    ("S2_2026_APRIL", "8/9 april"),
    ("S2_2026_MAY", "25 maj"),
    ("S2_2026_JUNE", "26/27 juni"),
    ("S2_2026_JULY", "9 juli"),
]
SOURCE_AUDIT_GPKG = "d2c_visual_audit_sample_100.gpkg"
OUTPUT_DIRNAME = "d2c_visual_audit_viewer_v1"
OUTPUT_HTML = "index.html"
OUTPUT_MANIFEST = "d2c_visual_audit_viewer_manifest.json"
OUTPUT_BLIND_KEY = "BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
BLIND_ORDER_SALT = "akerpuls-d2c-visual-audit-viewer-v1|2026-09-16"
BUFFER_M = 80.0
PANEL_PX = 380
HEADER_PX = 27
TITLE_PX = 38


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def blind_hash(fid: str) -> str:
    return hashlib.sha256(f"{BLIND_ORDER_SALT}|{fid}".encode("utf-8")).hexdigest()


def square_bounds(bounds: tuple[float, float, float, float], buffer_m: float = BUFFER_M) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = map(float, bounds)
    cx = 0.5 * (minx + maxx)
    cy = 0.5 * (miny + maxy)
    side = max(maxx - minx, maxy - miny) + 2.0 * float(buffer_m)
    if not np.isfinite(side) or side <= 0:
        raise RuntimeError(f"Invalid field bounds: {bounds}")
    half = 0.5 * side
    return cx - half, cy - half, cx + half, cy + half


def _shift_bool(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(a, dtype=bool)
    ys = slice(max(0, dy), a.shape[0] + min(0, dy))
    xs = slice(max(0, dx), a.shape[1] + min(0, dx))
    src_y = slice(max(0, -dy), a.shape[0] - max(0, dy))
    src_x = slice(max(0, -dx), a.shape[1] - max(0, dx))
    out[ys, xs] = a[src_y, src_x]
    return out


def boundary_and_halo(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = np.asarray(mask, dtype=bool)
    if m.ndim != 2:
        raise ValueError("mask must be 2D")
    eroded = m.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        eroded &= _shift_bool(m, dy, dx)
    boundary = m & ~eroded
    halo = boundary.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            halo |= _shift_bool(boundary, dy, dx)
    return boundary, halo


def joint_rgb_stretch(rgb_arrays: list[np.ndarray], valid_arrays: list[np.ndarray]) -> list[np.ndarray]:
    """Apply one robust per-channel stretch shared by all four dates for a field."""
    if len(rgb_arrays) != len(valid_arrays) or not rgb_arrays:
        raise ValueError("RGB/valid lists must be non-empty and aligned")
    lows: list[float] = []
    highs: list[float] = []
    for band in range(3):
        vals = []
        for rgb, valid in zip(rgb_arrays, valid_arrays):
            x = np.asarray(rgb[band], dtype=np.float32)
            m = np.asarray(valid, dtype=bool) & np.isfinite(x)
            if m.any():
                vals.append(x[m])
        if not vals:
            lows.append(0.0)
            highs.append(1.0)
            continue
        v = np.concatenate(vals)
        lo, hi = np.percentile(v, [2.0, 98.0])
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo + 1e-9:
            lo = float(np.nanmin(v))
            hi = float(np.nanmax(v))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo + 1e-9:
            lo, hi = 0.0, 1.0
        lows.append(float(lo))
        highs.append(float(hi))

    out: list[np.ndarray] = []
    for rgb in rgb_arrays:
        img = np.empty((rgb.shape[1], rgb.shape[2], 3), dtype=np.uint8)
        for band in range(3):
            x = (np.asarray(rgb[band], dtype=np.float32) - lows[band]) / (highs[band] - lows[band])
            x = np.clip(x, 0.0, 1.0)
            x = np.power(x, 0.90)
            img[..., band] = np.round(255.0 * x).astype(np.uint8)
        out.append(img)
    return out


def verify_d2c(d2c: Path) -> tuple[dict[str, Any], Path, str]:
    manifest_path = d2c / "d2c_manifest.json"
    freeze_path = d2c / "D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json"
    audit_path = d2c / SOURCE_AUDIT_GPKG
    for p in (manifest_path, freeze_path, audit_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    manifest = read_json(manifest_path)
    if manifest.get("status") != EXPECTED_D2C_STATUS:
        raise RuntimeError(f"D2C status changed: {manifest.get('status')}")
    if manifest.get("freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("D2C manifest freeze SHA changed")
    if sha256_file(freeze_path) != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("D2C freeze file SHA changed")
    rec = manifest.get("output_hashes", {}).get(SOURCE_AUDIT_GPKG)
    if not rec:
        raise RuntimeError(f"D2C manifest does not pin {SOURCE_AUDIT_GPKG}")
    audit_sha = sha256_file(audit_path)
    if audit_sha != rec.get("sha256"):
        raise RuntimeError("Frozen D2C audit GPKG SHA changed")
    return manifest, audit_path, audit_sha


def verify_d1(d1: Path, derived: Path) -> tuple[dict[str, Path], dict[str, str]]:
    manifest_path = d1 / "d1s3j_manifest.json"
    snap_index = d1 / "d1s3j_snapshot_outputs.csv"
    vrt_index = d1 / "d1s3j_vrt_outputs.csv"
    for p in (manifest_path, snap_index, vrt_index):
        if not p.is_file():
            raise FileNotFoundError(p)
    manifest = read_json(manifest_path)
    if manifest.get("status") != EXPECTED_D1_STATUS:
        raise RuntimeError(f"D1-S3j status changed: {manifest.get('status')}")
    if sha256_file(snap_index) != EXPECTED_D1_SNAPSHOT_INDEX_SHA256:
        raise RuntimeError("D1-S3j frozen snapshot output index SHA changed")
    if sha256_file(vrt_index) != EXPECTED_D1_VRT_INDEX_SHA256:
        raise RuntimeError("D1-S3j frozen VRT output index SHA changed")

    rows: dict[str, dict[str, str]] = {}
    with vrt_index.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows[str(row["snapshot"])] = row
    expected_names = {x[0] for x in SNAPSHOTS}
    if set(rows) != expected_names:
        raise RuntimeError(f"Frozen VRT snapshot set changed: {sorted(rows)}")

    vrt_paths: dict[str, Path] = {}
    vrt_hashes: dict[str, str] = {}
    for snap, _ in SNAPSHOTS:
        row = rows[snap]
        p = Path(row["path"])
        try:
            p.resolve().relative_to(derived.resolve())
        except Exception as exc:
            raise RuntimeError(f"VRT escaped frozen derived root: {p}") from exc
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        if got != row["sha256"]:
            raise RuntimeError(f"Frozen VRT SHA changed for {snap}")
        vrt_paths[snap] = p
        vrt_hashes[snap] = got
    return vrt_paths, vrt_hashes


def render_field_sheet(geom, vrt_paths: dict[str, Path], out_file: Path, blind_index: int) -> dict[str, float]:
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import from_bounds
    from PIL import Image, ImageDraw

    bounds = square_bounds(geom.bounds)
    rgb_arrays: list[np.ndarray] = []
    valid_arrays: list[np.ndarray] = []
    valid_fracs: dict[str, float] = {}
    window = None
    field_mask = None
    expected_grid = None

    for snap, _label in SNAPSHOTS:
        with rasterio.open(vrt_paths[snap]) as ds:
            desc = [str(x or "") for x in ds.descriptions]
            if desc != EXPECTED_BANDS:
                raise RuntimeError(f"Unexpected VRT band descriptions for {snap}: {desc}")
            if ds.crs is None or ds.crs.to_epsg() != EXPECTED_EPSG:
                raise RuntimeError(f"Unexpected VRT CRS for {snap}: {ds.crs}")
            grid = (ds.width, ds.height, tuple(ds.transform))
            if expected_grid is None:
                expected_grid = grid
                w = from_bounds(*bounds, transform=ds.transform)
                w = w.round_offsets().round_lengths()
                full = rasterio.windows.Window(0, 0, ds.width, ds.height)
                try:
                    window = w.intersection(full)
                except Exception as exc:
                    raise RuntimeError(f"Audit field outside frozen VRT extent: {bounds}") from exc
                if window.width < 2 or window.height < 2:
                    raise RuntimeError("Audit field crop is too small")
                window_transform = ds.window_transform(window)
                field_mask = rasterize(
                    [(geom, 1)],
                    out_shape=(int(window.height), int(window.width)),
                    transform=window_transform,
                    fill=0,
                    all_touched=True,
                    dtype="uint8",
                ).astype(bool)
                if not field_mask.any():
                    raise RuntimeError("Parent field did not rasterize into audit crop")
            elif grid != expected_grid:
                raise RuntimeError("Frozen snapshot VRT grids are not identical")

            band = {name: i + 1 for i, name in enumerate(desc)}
            rgb = np.stack([
                ds.read(band["B04"], window=window),
                ds.read(band["B03"], window=window),
                ds.read(band["B02"], window=window),
            ]).astype(np.float32, copy=False)
            valid = ds.read(band["VALID"], window=window) > 0.5
            rgb_arrays.append(rgb)
            valid_arrays.append(valid)
            denom = int(field_mask.sum())
            valid_fracs[snap] = float((valid & field_mask).sum() / denom) if denom else 0.0

    imgs = joint_rgb_stretch(rgb_arrays, valid_arrays)
    boundary, halo = boundary_and_halo(field_mask)

    panels = []
    for (snap, date_label), img, valid in zip(SNAPSHOTS, imgs, valid_arrays):
        bad = ~valid
        if bad.any():
            tint = np.array([255, 40, 80], dtype=np.float32)
            pix = img[bad].astype(np.float32)
            img[bad] = np.clip(0.35 * pix + 0.65 * tint, 0, 255).astype(np.uint8)
        img[halo] = np.array([0, 0, 0], dtype=np.uint8)
        img[boundary] = np.array([255, 255, 255], dtype=np.uint8)

        panel = Image.fromarray(img, mode="RGB").resize((PANEL_PX, PANEL_PX), resample=Image.Resampling.NEAREST)
        canvas = Image.new("RGB", (PANEL_PX, PANEL_PX + HEADER_PX), "white")
        canvas.paste(panel, (0, HEADER_PX))
        header = f"{date_label}   VALID fält={100.0 * valid_fracs[snap]:.1f}%"
        ImageDraw.Draw(canvas).text((6, 6), header, fill="black")
        panels.append(canvas)

    sheet = Image.new("RGB", (PANEL_PX * 4, PANEL_PX + HEADER_PX + TITLE_PX), "white")
    title = "ÅkerPuls blind audit #%03d   |   vit linje = officiell 2025-gräns   |   magenta = ej VALID" % blind_index
    ImageDraw.Draw(sheet).text((8, 10), title, fill="black")
    for i, panel in enumerate(panels):
        sheet.paste(panel, (PANEL_PX * i, TITLE_PX))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".partial.jpg")
    sheet.save(tmp, format="JPEG", quality=92, subsampling=0, optimize=True)
    tmp.replace(out_file)
    return valid_fracs


def build_html(items: list[dict[str, Any]], blind_key_sha256: str) -> str:
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls D2C – blind 100-fältsaudit</title>
<style>
:root{font-family:Arial,sans-serif;color:#171717;background:#f5f5f5} body{margin:0}.top{position:sticky;top:0;z-index:3;background:#fff;border-bottom:1px solid #ccc;padding:10px 14px}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.main{max-width:1600px;margin:12px auto;padding:0 12px 30px}.card{background:#fff;border:1px solid #ccc;border-radius:7px;padding:10px;box-shadow:0 1px 4px #bbb}.auditimg{display:block;width:100%;height:auto;background:#ddd}.labels{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.labels button,.nav button,#exportBtn{padding:9px 12px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}.labels button.sel{outline:3px solid #111;font-weight:bold}.note{width:100%;min-height:54px;box-sizing:border-box}.muted{color:#555;font-size:13px}.warn{font-weight:bold}.progress{font-variant-numeric:tabular-nums}.kbd{font-family:monospace;border:1px solid #aaa;border-radius:3px;padding:1px 4px;background:#eee}
</style></head><body>
<div class="top"><div class="row"><b>ÅkerPuls D2C – blind visuell audit</b><span id="pos" class="progress"></span><span id="done" class="progress"></span></div>
<div class="muted">Fråga: <b>Ser detta ut som två konsekvent olika odlingsregimer inom samma 2025-skifte över flera 2026-datum?</b> Ignorera spår/vändtegar/skuggor/diken och enstaka stress-/fuktfläckar. Fusion score och P95/P90-grupp är dolda.</div></div>
<div class="main"><div class="card">
<img id="img" class="auditimg" alt="blind audit field">
<div class="labels" id="labels"></div>
<textarea id="note" class="note" placeholder="Frivillig kort kommentar"></textarea>
<div class="row nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button><button id="exportBtn">Exportera frysta etiketter CSV</button><span class="muted">Tangenter <span class="kbd">1</span>–<span class="kbd">5</span> etikett, <span class="kbd">←</span>/<span class="kbd">→</span> navigera.</span></div>
<p class="muted warn">Öppna inte BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv före export. Etiketter lagras endast lokalt i denna webbläsare.</p>
</div></div>
<script>
const ITEMS=__ITEMS__;
const LABELS=['TYDLIG_SPLIT','MÖJLIG_SPLIT','TVEKSAM','FALSK_SPLIT','EJ_BEDÖMBAR'];
const FREEZE='__FREEZE__'; const KEY_SHA='__KEYSHA__';
const STORE='akerpuls_d2c_visual_audit_v1_'+FREEZE.slice(0,12)+'_'+KEY_SHA.slice(0,12);
let state=JSON.parse(localStorage.getItem(STORE)||'{}'); let idx=0;
function save(){localStorage.setItem(STORE,JSON.stringify(state));}
function cur(){return ITEMS[idx];}
function render(){const it=cur(); document.getElementById('img').src=it.image; document.getElementById('pos').textContent=`Fält ${idx+1}/${ITEMS.length} · blind #${String(it.blind_index).padStart(3,'0')}`; const rec=state[it.blind_index]||{}; document.getElementById('note').value=rec.note||''; const box=document.getElementById('labels'); box.innerHTML=''; LABELS.forEach((lab,i)=>{const b=document.createElement('button');b.textContent=`${i+1}. ${lab}`; if(rec.label===lab)b.classList.add('sel'); b.onclick=()=>{state[it.blind_index]={label:lab,note:document.getElementById('note').value};save();render();};box.appendChild(b);}); const n=ITEMS.filter(x=>state[x.blind_index]?.label).length; document.getElementById('done').textContent=`Bedömda ${n}/${ITEMS.length}`;}
document.getElementById('note').addEventListener('input',e=>{const it=cur();const rec=state[it.blind_index]||{};state[it.blind_index]={label:rec.label||'',note:e.target.value};save();});
document.getElementById('prev').onclick=()=>{idx=Math.max(0,idx-1);render();};document.getElementById('next').onclick=()=>{idx=Math.min(ITEMS.length-1,idx+1);render();};
document.addEventListener('keydown',e=>{if(document.activeElement===document.getElementById('note'))return;if(e.key>='1'&&e.key<='5'){const lab=LABELS[Number(e.key)-1];const it=cur();const rec=state[it.blind_index]||{};state[it.blind_index]={label:lab,note:rec.note||''};save();render();}else if(e.key==='ArrowRight'){idx=Math.min(ITEMS.length-1,idx+1);render();}else if(e.key==='ArrowLeft'){idx=Math.max(0,idx-1);render();}});
function q(s){return '"'+String(s??'').replaceAll('"','""')+'"';}
document.getElementById('exportBtn').onclick=()=>{const missing=ITEMS.filter(x=>!state[x.blind_index]?.label);if(missing.length&&!confirm(`${missing.length} fält saknar etikett. Exportera ändå?`))return;const rows=[['parent_d2c_freeze_sha256','blind_key_sha256','blind_index','label','note']];ITEMS.forEach(it=>{const r=state[it.blind_index]||{};rows.push([FREEZE,KEY_SHA,it.blind_index,r.label||'',r.note||'']);});const csv='\ufeff'+rows.map(r=>r.map(q).join(',')).join('\r\n')+'\r\n';const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='d2c_visual_audit_labels.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
render();
</script></body></html>'''
    return (
        template.replace("__ITEMS__", payload)
        .replace("__FREEZE__", EXPECTED_D2C_FREEZE_SHA256)
        .replace("__KEYSHA__", blind_key_sha256)
    )


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    ap.add_argument("--d1-dir", default=str(DEFAULT_D1))
    ap.add_argument("--derived-root", default=str(DEFAULT_DERIVED))
    args = ap.parse_args()

    head = git_guard()
    d2c = Path(args.d2c_dir)
    d1 = Path(args.d1_dir)
    derived = Path(args.derived_root)

    print("D2C_AUDIT_PROGRESS=VERIFY_FROZEN_D2C_AND_D1_LINEAGE", flush=True)
    _d2c_manifest, audit_path, audit_sha = verify_d2c(d2c)
    vrt_paths, vrt_hashes = verify_d1(d1, derived)

    print("D2C_AUDIT_PROGRESS=LOAD_AND_BLIND_100_FIELD_SAMPLE", flush=True)
    audit = gpd.read_file(audit_path)
    if len(audit) != EXPECTED_AUDIT_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_AUDIT_ROWS} audit fields, got {len(audit)}")
    required = {"parent_field_id_2025", "audit_group", "fusion_score", "qa_tier", "geometry"}
    missing = sorted(required - set(audit.columns))
    if missing:
        raise RuntimeError(f"Frozen audit sample missing columns: {missing}")
    audit["parent_field_id_2025"] = audit["parent_field_id_2025"].astype(str)
    if audit.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Frozen audit sample contains duplicate field IDs")
    counts = audit.audit_group.astype(str).value_counts().to_dict()
    if counts.get("P95_HIGH_PRIORITY", 0) != EXPECTED_P95_AUDIT or counts.get("P90_ONLY", 0) != EXPECTED_P90_ONLY_AUDIT:
        raise RuntimeError(f"Frozen audit strata changed: {counts}")
    audit = audit.to_crs(EXPECTED_EPSG)
    audit["blind_hash"] = [blind_hash(fid) for fid in audit.parent_field_id_2025]
    audit = audit.sort_values(["blind_hash", "parent_field_id_2025"]).reset_index(drop=True)
    audit["blind_index"] = np.arange(1, len(audit) + 1, dtype=int)

    out = d2c / OUTPUT_DIRNAME
    imgdir = out / "images"
    if out.exists():
        shutil.rmtree(out)
    imgdir.mkdir(parents=True, exist_ok=True)

    key_path = out / OUTPUT_BLIND_KEY
    key_fields = [
        "blind_index",
        "parent_field_id_2025",
        "audit_group",
        "qa_tier",
        "fusion_score",
        "prototype_p_splitmerge_2026",
        "separation_ratio",
        "true_loo_min_child_dice",
        "analysis_cell_id",
        "blind_hash",
    ]
    with key_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=key_fields)
        w.writeheader()
        for r in audit.itertuples(index=False):
            d = {k: getattr(r, k, "") for k in key_fields}
            w.writerow(d)
    blind_key_sha = sha256_file(key_path)

    print("D2C_AUDIT_PROGRESS=RENDER_100_X_4_FROZEN_SENTINEL_PANELS", flush=True)
    items: list[dict[str, Any]] = []
    image_hashes: dict[str, str] = {}
    field_validity: list[dict[str, Any]] = []
    for i, r in enumerate(audit.itertuples(index=False), 1):
        blind_index = int(r.blind_index)
        name = f"audit_{blind_index:03d}.jpg"
        dest = imgdir / name
        valid = render_field_sheet(r.geometry, vrt_paths, dest, blind_index)
        image_hashes[name] = sha256_file(dest)
        items.append({"blind_index": blind_index, "image": f"images/{name}"})
        field_validity.append({"blind_index": blind_index, **{k: float(v) for k, v in valid.items()}})
        if i == 1 or i % 10 == 0 or i == len(audit):
            print(f"D2C_AUDIT_RENDERED={i}/{len(audit)}", flush=True)

    html_path = out / OUTPUT_HTML
    write_text(html_path, build_html(items, blind_key_sha))
    validity_path = out / "blind_field_validity.json"
    write_json(validity_path, field_validity)

    manifest = {
        "schema_version": "akerpuls-d2c-visual-audit-viewer-v1",
        "status": "PASS_TO_BLIND_HUMAN_AUDIT",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_d2c_status": EXPECTED_D2C_STATUS,
        "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
        "parent_d2c_audit_gpkg": str(audit_path),
        "parent_d2c_audit_gpkg_sha256": audit_sha,
        "d1_status": EXPECTED_D1_STATUS,
        "d1_snapshot_output_index_sha256": EXPECTED_D1_SNAPSHOT_INDEX_SHA256,
        "d1_vrt_output_index_sha256": EXPECTED_D1_VRT_INDEX_SHA256,
        "vrt_paths": {k: str(v) for k, v in vrt_paths.items()},
        "vrt_sha256": vrt_hashes,
        "audit_fields": EXPECTED_AUDIT_ROWS,
        "hidden_strata": {"P95_HIGH_PRIORITY": EXPECTED_P95_AUDIT, "P90_ONLY": EXPECTED_P90_ONLY_AUDIT},
        "blind_order": "SHA256_SALTED_FIELD_ID",
        "blind_key": str(key_path),
        "blind_key_sha256": blind_key_sha,
        "html": str(html_path),
        "html_sha256": sha256_file(html_path),
        "validity_json": str(validity_path),
        "validity_json_sha256": sha256_file(validity_path),
        "image_count": len(image_hashes),
        "image_hashes": image_hashes,
        "rendering": {
            "same_extent_all_four_dates": True,
            "buffer_m": BUFFER_M,
            "rgb_bands": ["B04", "B03", "B02"],
            "stretch": "PER_FIELD_JOINT_4_DATE_PER_CHANNEL_P02_P98_GAMMA_0.90",
            "resampling_for_display": "NEAREST",
            "invalid_pixels": "MAGENTA_TINT",
            "boundary": "OFFICIAL_2025_WHITE_WITH_BLACK_HALO",
            "fusion_score_visible": False,
            "qa_tier_visible": False,
            "audit_group_visible": False,
        },
        "python_network_calls": 0,
        "browser_network_calls_required": False,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "split_line_generated": False,
        "merge_executed": False,
        "geometry_mutated": False,
        "d2c_frozen_artifacts_modified": False,
        "next_step": "Complete blind human labels for all 100 fields and export d2c_visual_audit_labels.csv before opening the blind key or computing P95/P90-only precision.",
    }
    write_json(out / OUTPUT_MANIFEST, manifest)

    print("AKERPULS D2C POST-FREEZE BLIND VISUAL AUDIT VIEWER")
    print("STATUS=PASS_TO_BLIND_HUMAN_AUDIT")
    print(f"PARENT_D2C_FREEZE_SHA256={EXPECTED_D2C_FREEZE_SHA256}")
    print(f"D1_SNAPSHOT_OUTPUT_INDEX_SHA256={EXPECTED_D1_SNAPSHOT_INDEX_SHA256}")
    print(f"D1_VRT_OUTPUT_INDEX_SHA256={EXPECTED_D1_VRT_INDEX_SHA256}")
    print(f"AUDIT_FIELDS={EXPECTED_AUDIT_ROWS} HIDDEN_P95={EXPECTED_P95_AUDIT} HIDDEN_P90_ONLY={EXPECTED_P90_ONLY_AUDIT}")
    print(f"BLIND_KEY_SHA256={blind_key_sha}")
    print("DO_NOT_OPEN_BLIND_KEY_BEFORE_REVIEW=TRUE")
    print("FUSION_SCORE_VISIBLE=FALSE QA_TIER_VISIBLE=FALSE AUDIT_GROUP_VISIBLE=FALSE")
    print("PYTHON_NETWORK_CALLS=0 BROWSER_NETWORK_REQUIRED=FALSE")
    print("MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE")
    print("SPLIT_LINE_GENERATED=FALSE GEOMETRY_MUTATED=FALSE D2C_FROZEN_ARTIFACTS_MODIFIED=FALSE")
    print(f"OUTPUT={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
