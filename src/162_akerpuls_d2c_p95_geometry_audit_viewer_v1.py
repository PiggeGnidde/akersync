#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a blind 100-field audit viewer for frozen P95 split-line proposals.

The source population is exactly the 613 P95 fields with a frozen primary split
line in P95_SPLIT_LINE_PROPOSAL_FREEZE_V1. A deterministic hash sample of 100 is
drawn before review. Field id, fusion score, prior human-audit labels and geometry
metrics are hidden from the HTML; they live only in a reveal key that must not be
opened until the 100 review labels have been exported.

Each audit item shows the same four frozen 2026 Sentinel-2 snapshots and the
official 2025 parent boundary plus the frozen primary review line. A diagnostic
view (raw K2 interface + two child-evidence regions) can be toggled, but no model,
threshold, fusion, smoothing, gap fill, merge or official-geometry replacement is
performed by this stage.
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
EXPECTED_PROPOSAL_FREEZE_STATUS = "FROZEN_P95_SPLIT_LINE_PROPOSALS_V1"
EXPECTED_PROPOSAL_FREEZE_SHA256 = "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a"
EXPECTED_SOURCE_PROPOSAL_MANIFEST_SHA256 = "c8aa8fedc73d723394eb1844358aefd7f60b0e5b163785d079d1876b1831d1a1"
EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"
EXPECTED_HUMAN_AUDIT_FREEZE_SHA256 = "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4"
EXPECTED_LINE_POPULATION = 613
EXPECTED_NO_INTERFACE = 5
EXPECTED_SAMPLE = 100
EXPECTED_D1_STATUS = "PASS_TO_FULL_SKANE_D1_RASTER_QA"
EXPECTED_D1_SNAPSHOT_INDEX_SHA256 = "a3a26d1f454a8c0d65e326a913b0d10d91c54d4ba9886315ec5d5dd1e35cafff"
EXPECTED_D1_VRT_INDEX_SHA256 = "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979"
EXPECTED_EPSG = 32633
EXPECTED_BANDS = ["B02", "B03", "B04", "B08", "B11", "SCL", "CLD", "VALID", "NDVI", "LSWI", "SOURCE_DATE_INDEX"]
SNAPSHOTS = [
    ("S2_2026_APRIL", "8/9 april"),
    ("S2_2026_MAY", "25 maj"),
    ("S2_2026_JUNE", "26/27 juni"),
    ("S2_2026_JULY", "9 juli"),
]
FREEZE_DIRNAME = "d2c_p95_split_line_freeze_v1"
FREEZE_NAME = "P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json"
FREEZE_MANIFEST = "p95_split_line_freeze_manifest.json"
OUTPUT_DIRNAME = "d2c_p95_geometry_audit_viewer_v1"
OUTPUT_HTML = "index.html"
OUTPUT_MANIFEST = "p95_geometry_audit_viewer_manifest.json"
OUTPUT_BLIND_KEY = "BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv"
SAMPLE_SALT = "akerpuls-p95-line-geometry-audit-sample-v1|2026-09-16|d3a06356"
BLIND_ORDER_SALT = "akerpuls-p95-line-geometry-audit-order-v1|2026-09-16|d3a06356"
BUFFER_M = 80.0
PANEL_PX = 380
HEADER_PX = 27
TITLE_PX = 42

SPLIT_LABELS = ["TYDLIG_SPLIT", "MÖJLIG_SPLIT", "TVEKSAM", "FALSK_SPLIT", "EJ_BEDÖMBAR"]
LINE_LABELS = ["RATT_GRANS", "NARA_GRANS", "FEL_GRANS", "EJ_BEDOMBAR", "EJ_TILLAMPLIG"]
PREDECLARED_ANALYSIS = {
    "split_positive_for_geometry": ["TYDLIG_SPLIT", "MÖJLIG_SPLIT"],
    "split_ambiguous": ["TVEKSAM"],
    "split_negative": ["FALSK_SPLIT"],
    "line_strict_positive": ["RATT_GRANS"],
    "line_broad_positive": ["RATT_GRANS", "NARA_GRANS"],
    "line_negative": ["FEL_GRANS"],
    "line_excluded": ["EJ_BEDOMBAR", "EJ_TILLAMPLIG"],
    "joint_strict_success": "split in {TYDLIG_SPLIT,MOJLIG_SPLIT} AND line=RATT_GRANS",
    "joint_broad_success": "split in {TYDLIG_SPLIT,MOJLIG_SPLIT} AND line in {RATT_GRANS,NARA_GRANS}",
}

REQUIRED_SOURCE_OUTPUTS = {
    "p95_split_proposal_summary.csv",
    "p95_b2_child_evidence_review.gpkg",
    "p95_official_2025_parents_review.gpkg",
    "p95_raw_k2_interface_review.gpkg",
    "p95_primary_split_line_review.gpkg",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def sample_hash(fid: str) -> str:
    return sha256_text(f"{SAMPLE_SALT}|{fid}")


def blind_hash(fid: str) -> str:
    return sha256_text(f"{BLIND_ORDER_SALT}|{fid}")


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


def mask_halo(mask: np.ndarray) -> np.ndarray:
    m = np.asarray(mask, dtype=bool)
    halo = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            halo |= _shift_bool(m, dy, dx)
    return halo


def joint_rgb_stretch(rgb_arrays: list[np.ndarray], valid_arrays: list[np.ndarray]) -> list[np.ndarray]:
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
            lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo + 1e-9:
            lo, hi = 0.0, 1.0
        lows.append(float(lo)); highs.append(float(hi))
    out: list[np.ndarray] = []
    for rgb in rgb_arrays:
        img = np.empty((rgb.shape[1], rgb.shape[2], 3), dtype=np.uint8)
        for band in range(3):
            x = (np.asarray(rgb[band], dtype=np.float32) - lows[band]) / (highs[band] - lows[band])
            x = np.power(np.clip(x, 0.0, 1.0), 0.90)
            img[..., band] = np.round(255.0 * x).astype(np.uint8)
        out.append(img)
    return out


def verify_proposal_freeze(d2c: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    freeze_dir = d2c / FREEZE_DIRNAME
    freeze_path = freeze_dir / FREEZE_NAME
    manifest_path = freeze_dir / FREEZE_MANIFEST
    for p in (freeze_path, manifest_path):
        if not p.is_file():
            raise FileNotFoundError(p)
    if sha256_file(freeze_path) != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("P95 split-line proposal freeze SHA changed")
    freeze = read_json(freeze_path)
    manifest = read_json(manifest_path)
    if freeze.get("status") != EXPECTED_PROPOSAL_FREEZE_STATUS or manifest.get("status") != EXPECTED_PROPOSAL_FREEZE_STATUS:
        raise RuntimeError("P95 proposal freeze status changed")
    if manifest.get("proposal_freeze_sha256") != EXPECTED_PROPOSAL_FREEZE_SHA256:
        raise RuntimeError("P95 proposal freeze manifest binding changed")
    if freeze.get("source_proposal_manifest_sha256") != EXPECTED_SOURCE_PROPOSAL_MANIFEST_SHA256:
        raise RuntimeError("Source proposal manifest SHA changed")
    if freeze.get("parent_d2c_freeze_sha256") != EXPECTED_D2C_FREEZE_SHA256:
        raise RuntimeError("Proposal freeze parent D2C binding changed")
    if freeze.get("parent_human_audit_freeze_sha256") != EXPECTED_HUMAN_AUDIT_FREEZE_SHA256:
        raise RuntimeError("Proposal freeze parent human-audit binding changed")
    if int(freeze.get("line_available_fields", -1)) != EXPECTED_LINE_POPULATION or int(freeze.get("no_shared_interface_fields", -1)) != EXPECTED_NO_INTERFACE:
        raise RuntimeError("Proposal freeze line census changed")
    guards = freeze.get("guards", {})
    must_false = ["model_executed", "thresholds_tuned", "fusion_refit", "merge_executed", "smoothing", "gap_filling", "official_2025_geometry_replaced", "automatic_geometry_mutation"]
    if any(guards.get(k) is not False for k in must_false) or guards.get("review_only") is not True:
        raise RuntimeError(f"Proposal freeze guards changed: {guards}")
    outputs = freeze.get("source_output_hashes", {})
    if set(outputs) != REQUIRED_SOURCE_OUTPUTS:
        raise RuntimeError(f"Proposal freeze source output set changed: {sorted(outputs)}")
    paths: dict[str, Path] = {}
    for name in sorted(REQUIRED_SOURCE_OUTPUTS):
        rec = outputs[name]
        p = Path(rec["path"])
        if not p.is_file():
            raise FileNotFoundError(p)
        if sha256_file(p) != rec.get("sha256") or int(p.stat().st_size) != int(rec.get("bytes", -1)):
            raise RuntimeError(f"Frozen proposal output changed: {name}")
        paths[name] = p
    return freeze, paths


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
        p = Path(rows[snap]["path"])
        try:
            p.resolve().relative_to(derived.resolve())
        except Exception as exc:
            raise RuntimeError(f"VRT escaped frozen derived root: {p}") from exc
        if not p.is_file():
            raise FileNotFoundError(p)
        got = sha256_file(p)
        if got != rows[snap]["sha256"]:
            raise RuntimeError(f"Frozen VRT SHA changed for {snap}")
        vrt_paths[snap] = p; vrt_hashes[snap] = got
    return vrt_paths, vrt_hashes


def render_field_sheets(parent_geom, primary_line, raw_line, child_geoms: list[Any], vrt_paths: dict[str, Path], primary_file: Path, diagnostic_file: Path, blind_index: int) -> dict[str, float]:
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import from_bounds
    from PIL import Image, ImageDraw

    bounds = square_bounds(parent_geom.bounds)
    rgb_arrays: list[np.ndarray] = []
    valid_arrays: list[np.ndarray] = []
    valid_fracs: dict[str, float] = {}
    window = None; parent_mask = None; line_mask = None; raw_mask = None; child_mask = None
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
                w = from_bounds(*bounds, transform=ds.transform).round_offsets().round_lengths()
                full = rasterio.windows.Window(0, 0, ds.width, ds.height)
                try:
                    window = w.intersection(full)
                except Exception as exc:
                    raise RuntimeError(f"Audit field outside frozen VRT extent: {bounds}") from exc
                if window.width < 2 or window.height < 2:
                    raise RuntimeError("Audit field crop is too small")
                tr = ds.window_transform(window)
                shape = (int(window.height), int(window.width))
                parent_mask = rasterize([(parent_geom, 1)], out_shape=shape, transform=tr, fill=0, all_touched=True, dtype="uint8").astype(bool)
                line_mask = rasterize([(primary_line, 1)], out_shape=shape, transform=tr, fill=0, all_touched=True, dtype="uint8").astype(bool)
                raw_mask = rasterize([(raw_line, 1)], out_shape=shape, transform=tr, fill=0, all_touched=True, dtype="uint8").astype(bool)
                child_mask = rasterize([(g, i + 1) for i, g in enumerate(child_geoms)], out_shape=shape, transform=tr, fill=0, all_touched=True, dtype="uint8")
                if not parent_mask.any() or not line_mask.any():
                    raise RuntimeError("Parent or primary split-line failed to rasterize")
            elif grid != expected_grid:
                raise RuntimeError("Frozen snapshot VRT grids are not identical")
            band = {name: i + 1 for i, name in enumerate(desc)}
            rgb = np.stack([ds.read(band["B04"], window=window), ds.read(band["B03"], window=window), ds.read(band["B02"], window=window)]).astype(np.float32, copy=False)
            valid = ds.read(band["VALID"], window=window) > 0.5
            rgb_arrays.append(rgb); valid_arrays.append(valid)
            denom = int(parent_mask.sum())
            valid_fracs[snap] = float((valid & parent_mask).sum() / denom) if denom else 0.0

    imgs = joint_rgb_stretch(rgb_arrays, valid_arrays)
    parent_boundary, parent_halo = boundary_and_halo(parent_mask)
    line_halo = mask_halo(line_mask)
    raw_halo = mask_halo(raw_mask)

    primary_panels = []; diagnostic_panels = []
    for (snap, date_label), base, valid in zip(SNAPSHOTS, imgs, valid_arrays):
        img = base.copy()
        bad = ~valid
        if bad.any():
            tint = np.array([255, 40, 80], dtype=np.float32)
            img[bad] = np.clip(0.35 * img[bad].astype(np.float32) + 0.65 * tint, 0, 255).astype(np.uint8)
        img[parent_halo] = np.array([0, 0, 0], dtype=np.uint8)
        img[parent_boundary] = np.array([255, 255, 255], dtype=np.uint8)
        img[line_halo & ~line_mask] = np.array([0, 0, 0], dtype=np.uint8)
        img[line_mask] = np.array([0, 255, 255], dtype=np.uint8)

        diag = base.copy()
        if bad.any():
            tint = np.array([255, 40, 80], dtype=np.float32)
            diag[bad] = np.clip(0.35 * diag[bad].astype(np.float32) + 0.65 * tint, 0, 255).astype(np.uint8)
        for val, tint in ((1, np.array([40, 120, 255], dtype=np.float32)), (2, np.array([255, 170, 20], dtype=np.float32))):
            m = child_mask == val
            if m.any():
                diag[m] = np.clip(0.70 * diag[m].astype(np.float32) + 0.30 * tint, 0, 255).astype(np.uint8)
        diag[parent_halo] = np.array([0, 0, 0], dtype=np.uint8)
        diag[parent_boundary] = np.array([255, 255, 255], dtype=np.uint8)
        diag[raw_halo & ~raw_mask] = np.array([0, 0, 0], dtype=np.uint8)
        diag[raw_mask] = np.array([255, 255, 0], dtype=np.uint8)
        diag[line_mask] = np.array([0, 255, 255], dtype=np.uint8)

        def panel(arr):
            p = Image.fromarray(arr, mode="RGB").resize((PANEL_PX, PANEL_PX), resample=Image.Resampling.NEAREST)
            c = Image.new("RGB", (PANEL_PX, PANEL_PX + HEADER_PX), "white"); c.paste(p, (0, HEADER_PX))
            ImageDraw.Draw(c).text((6, 6), f"{date_label}   VALID fält={100.0 * valid_fracs[snap]:.1f}%", fill="black")
            return c
        primary_panels.append(panel(img)); diagnostic_panels.append(panel(diag))

    def save_sheet(panels, dest: Path, diagnostic: bool) -> None:
        sheet = Image.new("RGB", (PANEL_PX * 4, PANEL_PX + HEADER_PX + TITLE_PX), "white")
        if diagnostic:
            title = "ÅkerPuls geometry audit #%03d | vit=2025 | cyan=primär | gul=rå K2 | blå/orange=child evidence" % blind_index
        else:
            title = "ÅkerPuls geometry audit #%03d | vit=officiell 2025-gräns | cyan=föreslagen 2026 split-line | magenta=ej VALID" % blind_index
        ImageDraw.Draw(sheet).text((8, 10), title, fill="black")
        for i, p in enumerate(panels):
            sheet.paste(p, (PANEL_PX * i, TITLE_PX))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".partial.jpg")
        sheet.save(tmp, format="JPEG", quality=92, subsampling=0, optimize=True)
        tmp.replace(dest)
    save_sheet(primary_panels, primary_file, False)
    save_sheet(diagnostic_panels, diagnostic_file, True)
    return valid_fracs


def build_html(items: list[dict[str, Any]], blind_key_sha256: str) -> str:
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    split_labels = json.dumps(SPLIT_LABELS, ensure_ascii=False)
    line_labels = json.dumps(LINE_LABELS, ensure_ascii=False)
    template = r'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerPuls – blind P95 line-geometri-audit</title><style>
:root{font-family:Arial,sans-serif;color:#171717;background:#f5f5f5}body{margin:0}.top{position:sticky;top:0;z-index:3;background:#fff;border-bottom:1px solid #ccc;padding:10px 14px}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.main{max-width:1600px;margin:12px auto;padding:0 12px 30px}.card{background:#fff;border:1px solid #ccc;border-radius:7px;padding:10px;box-shadow:0 1px 4px #bbb}.auditimg{display:block;width:100%;height:auto;background:#ddd}.labels{display:flex;gap:7px;flex-wrap:wrap;margin:7px 0 12px}.labels button,.nav button,#exportBtn,#toggleBtn{padding:8px 11px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}.labels button.sel{outline:3px solid #111;font-weight:bold}.q{font-weight:bold;margin-top:10px}.note{width:100%;min-height:54px;box-sizing:border-box}.muted{color:#555;font-size:13px}.warn{font-weight:bold}.progress{font-variant-numeric:tabular-nums}.kbd{font-family:monospace;border:1px solid #aaa;border-radius:3px;padding:1px 4px;background:#eee}
</style></head><body><div class="top"><div class="row"><b>ÅkerPuls – blind P95 split-line geometri-audit</b><span id="pos" class="progress"></span><span id="done" class="progress"></span><button id="toggleBtn">Visa diagnostik</button></div>
<div class="muted">Bedöm bara vad som händer <b>innanför den vita 2025-gränsen</b>. Cyan linje är den frysta föreslagna split-linjen. Field-id, fusion score, tidigare human-audit och geometri-mått är dolda.</div></div>
<div class="main"><div class="card"><img id="img" class="auditimg" alt="blind geometry audit field">
<div class="q">A. Finns en verklig intern 2026-split?</div><div class="labels" id="splitLabels"></div>
<div class="q">B. Om split finns: följer cyan linje den verkliga gränsen?</div><div class="labels" id="lineLabels"></div>
<textarea id="note" class="note" placeholder="Frivillig kort kommentar"></textarea>
<div class="row nav"><button id="prev">← Föregående</button><button id="next">Nästa →</button><button id="exportBtn">Exportera geometri-audit CSV</button><span class="muted">1–5 = split. A/S/D/F/G = linjekvalitet. ←/→ = navigera.</span></div>
<p class="muted">Linjekvalitet: <b>RATT_GRANS</b> ≈ följer rätt intern gräns inom satellitens ~10 m upplösning; <b>NARA_GRANS</b> = huvudsakligen rätt men märkbart förskjuten/fragmenterad; <b>FEL_GRANS</b> = fel läge/orientering. Välj <b>EJ_TILLAMPLIG</b> när någon verklig split inte finns.</p>
<p class="muted warn">Öppna inte BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv före export. Diagnostikvyn visar rå K2-interface och child-evidence men inga score eller tidigare humanetiketter.</p></div></div>
<script>
const ITEMS=__ITEMS__; const SPLIT=__SPLIT__; const LINE=__LINE__; const FREEZE='__FREEZE__'; const KEY_SHA='__KEYSHA__';
const STORE='akerpuls_p95_geometry_audit_v1_'+FREEZE.slice(0,12)+'_'+KEY_SHA.slice(0,12); let state=JSON.parse(localStorage.getItem(STORE)||'{}'); let idx=0; let diagnostic=false;
function save(){localStorage.setItem(STORE,JSON.stringify(state));} function cur(){return ITEMS[idx];}
function setRec(k,v){const it=cur();const r=state[it.blind_index]||{};r[k]=v;r.note=document.getElementById('note').value;state[it.blind_index]=r;save();render();}
function buttons(id,labels,key){const box=document.getElementById(id);box.innerHTML='';const rec=state[cur().blind_index]||{};labels.forEach((lab,i)=>{const b=document.createElement('button');b.textContent=lab;if(rec[key]===lab)b.classList.add('sel');b.onclick=()=>setRec(key,lab);box.appendChild(b);});}
function render(){const it=cur();document.getElementById('img').src=diagnostic?it.diagnostic_image:it.primary_image;document.getElementById('toggleBtn').textContent=diagnostic?'Visa primärvy':'Visa diagnostik';document.getElementById('pos').textContent=`Fält ${idx+1}/${ITEMS.length} · blind #${String(it.blind_index).padStart(3,'0')}`;const r=state[it.blind_index]||{};document.getElementById('note').value=r.note||'';buttons('splitLabels',SPLIT,'split_label');buttons('lineLabels',LINE,'line_label');const n=ITEMS.filter(x=>state[x.blind_index]?.split_label&&state[x.blind_index]?.line_label).length;document.getElementById('done').textContent=`Kompletta ${n}/${ITEMS.length}`;}
document.getElementById('toggleBtn').onclick=()=>{diagnostic=!diagnostic;render();};document.getElementById('note').addEventListener('input',e=>{const it=cur();const r=state[it.blind_index]||{};r.note=e.target.value;state[it.blind_index]=r;save();});document.getElementById('prev').onclick=()=>{idx=Math.max(0,idx-1);render();};document.getElementById('next').onclick=()=>{idx=Math.min(ITEMS.length-1,idx+1);render();};
document.addEventListener('keydown',e=>{if(document.activeElement===document.getElementById('note'))return;if(e.key>='1'&&e.key<='5'){setRec('split_label',SPLIT[Number(e.key)-1]);return;}const m={a:0,s:1,d:2,f:3,g:4};if(m[e.key.toLowerCase()]!==undefined){setRec('line_label',LINE[m[e.key.toLowerCase()]]);return;}if(e.key==='ArrowRight'){idx=Math.min(ITEMS.length-1,idx+1);render();}else if(e.key==='ArrowLeft'){idx=Math.max(0,idx-1);render();}});
function q(s){return '"'+String(s??'').replaceAll('"','""')+'"';}
document.getElementById('exportBtn').onclick=()=>{const missing=ITEMS.filter(x=>!state[x.blind_index]?.split_label||!state[x.blind_index]?.line_label);if(missing.length&&!confirm(`${missing.length} fält saknar komplett dubbelbedömning. Exportera ändå?`))return;const rows=[['parent_proposal_freeze_sha256','blind_key_sha256','blind_index','split_label','line_label','note']];ITEMS.forEach(it=>{const r=state[it.blind_index]||{};rows.push([FREEZE,KEY_SHA,it.blind_index,r.split_label||'',r.line_label||'',r.note||'']);});const csv='\ufeff'+rows.map(r=>r.map(q).join(',')).join('\r\n')+'\r\n';const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='p95_geometry_audit_labels.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};render();
</script></body></html>'''
    return (template.replace("__ITEMS__", payload).replace("__SPLIT__", split_labels).replace("__LINE__", line_labels).replace("__FREEZE__", EXPECTED_PROPOSAL_FREEZE_SHA256).replace("__KEYSHA__", blind_key_sha256))


def main() -> int:
    import geopandas as gpd
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--d2c-dir", default=str(DEFAULT_D2C))
    ap.add_argument("--d1-dir", default=str(DEFAULT_D1))
    ap.add_argument("--derived-root", default=str(DEFAULT_DERIVED))
    args = ap.parse_args()
    head = git_guard(); d2c = Path(args.d2c_dir); d1 = Path(args.d1_dir); derived = Path(args.derived_root)

    print("P95_GEOMETRY_AUDIT_PROGRESS=VERIFY_PROPOSAL_FREEZE_AND_D1_LINEAGE", flush=True)
    freeze, src = verify_proposal_freeze(d2c)
    vrt_paths, vrt_hashes = verify_d1(d1, derived)

    summary = pd.read_csv(src["p95_split_proposal_summary.csv"], encoding="utf-8-sig", dtype={"parent_field_id_2025": str})
    lines = gpd.read_file(src["p95_primary_split_line_review.gpkg"]).to_crs(EXPECTED_EPSG)
    raw = gpd.read_file(src["p95_raw_k2_interface_review.gpkg"]).to_crs(EXPECTED_EPSG)
    parents = gpd.read_file(src["p95_official_2025_parents_review.gpkg"]).to_crs(EXPECTED_EPSG)
    children = gpd.read_file(src["p95_b2_child_evidence_review.gpkg"]).to_crs(EXPECTED_EPSG)
    for df in (summary, lines, raw, parents, children):
        if "parent_field_id_2025" not in df.columns:
            raise RuntimeError("Frozen proposal artifact missing parent_field_id_2025")
        df["parent_field_id_2025"] = df.parent_field_id_2025.astype(str)

    line_ids = summary.loc[summary.proposal_status.astype(str).eq("LINE_AVAILABLE"), "parent_field_id_2025"].astype(str).tolist()
    if len(line_ids) != EXPECTED_LINE_POPULATION or len(set(line_ids)) != EXPECTED_LINE_POPULATION:
        raise RuntimeError("Frozen LINE_AVAILABLE population is not exactly 613 unique fields")
    if len(lines) != EXPECTED_LINE_POPULATION or lines.parent_field_id_2025.duplicated().any() or set(lines.parent_field_id_2025) != set(line_ids):
        raise RuntimeError("Primary line GPKG population differs from frozen 613-line census")
    if len(raw) != EXPECTED_LINE_POPULATION or raw.parent_field_id_2025.duplicated().any() or set(raw.parent_field_id_2025) != set(line_ids):
        raise RuntimeError("Raw-interface GPKG population differs from frozen 613-line census")
    if len(parents) != 618 or parents.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Official-parent review GPKG is not 618 unique P95 fields")
    child_counts = children.parent_field_id_2025.value_counts().to_dict()
    if len(children) != 1236 or any(int(child_counts.get(fid, 0)) != 2 for fid in parents.parent_field_id_2025):
        raise RuntimeError("Child-evidence GPKG is not exactly two features per P95 parent")

    print("P95_GEOMETRY_AUDIT_PROGRESS=DETERMINISTIC_HASH_SAMPLE_100_OF_613", flush=True)
    sample = pd.DataFrame({"parent_field_id_2025": line_ids})
    sample["sample_hash"] = [sample_hash(fid) for fid in sample.parent_field_id_2025]
    sample = sample.sort_values(["sample_hash", "parent_field_id_2025"]).head(EXPECTED_SAMPLE).copy()
    if len(sample) != EXPECTED_SAMPLE or sample.parent_field_id_2025.duplicated().any():
        raise RuntimeError("Geometry audit sample is not 100 unique fields")
    sample["blind_hash"] = [blind_hash(fid) for fid in sample.parent_field_id_2025]
    sample = sample.sort_values(["blind_hash", "parent_field_id_2025"]).reset_index(drop=True)
    sample["blind_index"] = np.arange(1, EXPECTED_SAMPLE + 1, dtype=int)
    sample_population_sha = sha256_text("\n".join(sorted(sample.parent_field_id_2025.astype(str))) + "\n")

    summary_idx = summary.set_index("parent_field_id_2025", drop=False)
    parents_idx = parents.set_index("parent_field_id_2025", drop=False)
    lines_idx = lines.set_index("parent_field_id_2025", drop=False)
    raw_idx = raw.set_index("parent_field_id_2025", drop=False)
    child_groups = {fid: grp.sort_values("cluster") if "cluster" in grp.columns else grp for fid, grp in children.groupby("parent_field_id_2025")}

    out = d2c / OUTPUT_DIRNAME
    if out.exists():
        shutil.rmtree(out)
    imgdir = out / "images"; imgdir.mkdir(parents=True, exist_ok=True)

    key_path = out / OUTPUT_BLIND_KEY
    key_fields = ["blind_index", "parent_field_id_2025", "sample_hash", "blind_hash", "analysis_cell_id", "fusion_score", "separation_ratio", "spatial_coherence", "min_child_fraction", "min_child_pixels", "supporting_snapshots", "raw_interface_length_m", "primary_line_length_m", "primary_fraction_of_raw"]
    with key_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=key_fields); w.writeheader()
        for r in sample.itertuples(index=False):
            s = summary_idx.loc[str(r.parent_field_id_2025)]
            w.writerow({k: (getattr(r, k) if hasattr(r, k) else s.get(k, "")) for k in key_fields})
    blind_key_sha = sha256_file(key_path)

    print("P95_GEOMETRY_AUDIT_PROGRESS=RENDER_100_X_4_PRIMARY_AND_DIAGNOSTIC", flush=True)
    items: list[dict[str, Any]] = []; image_hashes: dict[str, str] = {}; validity_rows: list[dict[str, Any]] = []
    for i, r in enumerate(sample.itertuples(index=False), 1):
        fid = str(r.parent_field_id_2025); bi = int(r.blind_index)
        parent_geom = parents_idx.loc[fid].geometry; primary_line = lines_idx.loc[fid].geometry; raw_line = raw_idx.loc[fid].geometry
        cgeoms = list(child_groups[fid].geometry)
        if len(cgeoms) != 2:
            raise RuntimeError(f"Expected two child geometries for {fid}")
        p_name = f"audit_{bi:03d}_primary.jpg"; d_name = f"audit_{bi:03d}_diagnostic.jpg"
        p_dest = imgdir / p_name; d_dest = imgdir / d_name
        valid = render_field_sheets(parent_geom, primary_line, raw_line, cgeoms, vrt_paths, p_dest, d_dest, bi)
        image_hashes[p_name] = sha256_file(p_dest); image_hashes[d_name] = sha256_file(d_dest)
        items.append({"blind_index": bi, "primary_image": f"images/{p_name}", "diagnostic_image": f"images/{d_name}"})
        validity_rows.append({"blind_index": bi, **{k: float(v) for k, v in valid.items()}})
        if i == 1 or i % 10 == 0 or i == EXPECTED_SAMPLE:
            print(f"P95_GEOMETRY_AUDIT_RENDERED={i}/{EXPECTED_SAMPLE}", flush=True)

    html_path = out / OUTPUT_HTML; write_text(html_path, build_html(items, blind_key_sha))
    validity_path = out / "blind_field_validity.json"; write_json(validity_path, validity_rows)
    manifest = {
        "schema_version": "akerpuls-d2c-p95-geometry-audit-viewer-v1",
        "status": "PASS_TO_BLIND_P95_LINE_GEOMETRY_AUDIT",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "parent_proposal_freeze_sha256": EXPECTED_PROPOSAL_FREEZE_SHA256,
        "parent_source_proposal_manifest_sha256": EXPECTED_SOURCE_PROPOSAL_MANIFEST_SHA256,
        "parent_d2c_freeze_sha256": EXPECTED_D2C_FREEZE_SHA256,
        "parent_human_audit_freeze_sha256": EXPECTED_HUMAN_AUDIT_FREEZE_SHA256,
        "line_population": EXPECTED_LINE_POPULATION,
        "audit_sample": EXPECTED_SAMPLE,
        "sample_method": "LOWEST_SHA256_HASH_100_OF_613_WITH_FROZEN_SAMPLE_SALT",
        "sample_salt": SAMPLE_SALT,
        "blind_order_salt": BLIND_ORDER_SALT,
        "sample_population_sha256": sample_population_sha,
        "blind_key_sha256": blind_key_sha,
        "predeclared_analysis": PREDECLARED_ANALYSIS,
        "rendering_contract": {"snapshots": [x[0] for x in SNAPSHOTS], "common_square_extent_per_field": True, "buffer_m": BUFFER_M, "joint_p02_p98_rgb_stretch_across_four_dates": True, "gamma": 0.90, "nearest_display": True, "parent_boundary": "WHITE_WITH_BLACK_HALO", "primary_split_line": "CYAN_WITH_BLACK_HALO", "invalid_pixels": "MAGENTA_TINT", "diagnostic_raw_interface": "YELLOW", "diagnostic_children": "BLUE_ORANGE_30_PERCENT_TINT"},
        "d1_snapshot_output_index_sha256": EXPECTED_D1_SNAPSHOT_INDEX_SHA256,
        "d1_vrt_output_index_sha256": EXPECTED_D1_VRT_INDEX_SHA256,
        "vrt_hashes": vrt_hashes,
        "html_sha256": sha256_file(html_path),
        "blind_field_validity_sha256": sha256_file(validity_path),
        "image_hashes": image_hashes,
        "fusion_score_visible": False,
        "field_id_visible": False,
        "previous_human_audit_visible": False,
        "geometry_metrics_visible": False,
        "python_network_calls": 0,
        "browser_network_required": False,
        "model_executed": False,
        "thresholds_tuned": False,
        "fusion_refit": False,
        "smoothing": False,
        "gap_filling": False,
        "merge_executed": False,
        "official_2025_geometry_replaced": False,
        "automatic_geometry_mutation": False,
        "review_only": True,
    }
    manifest_path = out / OUTPUT_MANIFEST; write_json(manifest_path, manifest)
    print("AKERPULS D2C P95 BLIND LINE-GEOMETRY AUDIT VIEWER")
    print("STATUS=PASS_TO_BLIND_P95_LINE_GEOMETRY_AUDIT")
    print(f"PARENT_PROPOSAL_FREEZE_SHA256={EXPECTED_PROPOSAL_FREEZE_SHA256}")
    print(f"LINE_POPULATION={EXPECTED_LINE_POPULATION} AUDIT_SAMPLE={EXPECTED_SAMPLE}")
    print(f"SAMPLE_POPULATION_SHA256={sample_population_sha}")
    print(f"BLIND_KEY_SHA256={blind_key_sha}")
    print("FIELD_ID_VISIBLE=FALSE FUSION_SCORE_VISIBLE=FALSE PREVIOUS_HUMAN_AUDIT_VISIBLE=FALSE GEOMETRY_METRICS_VISIBLE=FALSE")
    print("PYTHON_NETWORK_CALLS=0 BROWSER_NETWORK_REQUIRED=FALSE MODEL_EXECUTED=FALSE THRESHOLDS_TUNED=FALSE FUSION_REFIT=FALSE")
    print("SMOOTHING=FALSE GAP_FILLING=FALSE OFFICIAL_2025_GEOMETRY_REPLACED=FALSE REVIEW_ONLY=TRUE")
    print(f"DO_NOT_OPEN_BLIND_KEY_BEFORE_REVIEW=TRUE")
    print(f"OUTPUT={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
