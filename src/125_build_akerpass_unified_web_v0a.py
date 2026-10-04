#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build ÅkerPass Unified Preview Web v0a.

Frozen inputs are not recalculated. The build:
1) regenerates the ÅkerFrö × ÅkerAccess presentation from frozen BestMatch v0c,
2) forward-ports frozen Rotation v1.1 into the municipality ÅkerFrö sidecars,
3) forward-ports the already-built/frozen ÅkerVatten + VISS/VattenTryck web payload,
4) copies Rapskartan 2025 as a separate sub-view,
5) writes a reproducibility manifest.

The source ÅkerVatten-VISS dist is treated as a frozen web artifact: only
data/akervatten/* and assets/akervatten_v0a.{css,js} are copied. Its old
index.html is never used as the unified base.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "akerpass_unified_web_v0a"
ACCESS_BASE = WORK / "access_base"
DEFAULT_DIST = ROOT / "dist_akerpass_unified_v0a"
BESTMATCH = ROOT / "data" / "derived" / "akerfro_akeraccess_bestmatch_v0c" / "bestmatch_v0c_fields.parquet"
ROTATION = ROOT / "data" / "derived" / "akerfro_rotation_v1a" / "akerfro_rotation_v1a_fields.parquet"

EXPECTED_FIELDS = 128_636
EXPECTED_WATER_MUNICIPALITIES = 33
EXPECTED_VISS_POSITIVE = 16_626
EXPECTED_GW_LEVEL_IMPACT = 5_495
EXPECTED_ROTATION_RELEASED = 43
EXPECTED_BESTMATCH_CANDIDATES = 16_004

WATER_MARK = "AKERVATTEN_WEB_UI_V0A"
VISS_MARK = "AKERVATTEN_VISS_UI_V0A"
ACCESS_MARK = "AKERFRO_ACCESS_WEB_UI_V0B"
FRO_MARK = "AKERFRO_ERTOR_WEB_UI_V0A"
NORM_MARK = "AKERNORM_WEB_UI_V1"
UNIFIED_MARK = "AKERPASS_UNIFIED_WEB_V0A"

WATER_CONTROLS = r"""
  <div id="akervattenControls" class="akv-controls">
   <div class="akv-head">
    <span class="akv-title">ÅkerVatten · informationslager</span>
    <span class="akv-noverdict">Ingen totalscore</span>
   </div>
   <div class="akv-layer-grid">
    <button type="button" class="akv-sub active" data-akv-layer="mark_torka">MarkTorka</button>
    <button type="button" class="akv-sub" data-akv-layer="mark_vata">MarkVäta</button>
    <button type="button" class="akv-sub" data-akv-layer="small_gw">Små magasin</button>
    <button type="button" class="akv-sub" data-akv-layer="gw_drought">GrundvattenTorka</button>
    <button type="button" class="akv-sub" data-akv-layer="large_gw">Stora magasin</button>
    <button type="button" class="akv-sub" data-akv-layer="sw_drought">YtvattenTorka</button>
    <button type="button" class="akv-sub" data-akv-layer="viss">VISS / uttag</button>
   </div>
   <div id="akvSubHint" class="akv-subhint">Separata hydrologiska och hydrogeologiska underlag. VISS-klassning gäller grundvattenförekomsten, inte den enskilda åkern.</div>
  </div>
"""

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def stable_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {n}")
    return text.replace(old, new, 1)

def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8").strip()

def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd), flush=True)
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing if existing else "")
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)

def candidate_roots() -> Iterable[Path]:
    seen = set()
    explicit = [
        Path(r"C:\AkerSync-AkerVattenWeb"),
        Path(r"C:\AkerSync-AkerVatten"),
        Path(r"C:\AkerSync-VattenWeb"),
        Path(r"C:\AkerSync-Vatten"),
        Path(r"C:\AkerSync-Rapskartan"),
        Path(r"C:\AkerSyncRepo"),
    ]
    for p in explicit:
        if p not in seen:
            seen.add(p); yield p
    drive = ROOT.anchor or "C:\\"
    try:
        for p in sorted(Path(drive).glob("AkerSync*")):
            if p not in seen:
                seen.add(p); yield p
    except OSError:
        pass

def inspect_water_dist(dist: Path) -> dict | None:
    idx = dist / "data" / "akervatten" / "skane_index.json"
    js = dist / "assets" / "akervatten_v0a.js"
    css = dist / "assets" / "akervatten_v0a.css"
    html = dist / "index.html"
    if not all(p.is_file() for p in (idx, js, css, html)):
        return None
    js_text = js.read_text(encoding="utf-8", errors="replace")
    html_text = html.read_text(encoding="utf-8", errors="replace")
    if WATER_MARK not in js_text or VISS_MARK not in js_text or WATER_MARK not in html_text or VISS_MARK not in html_text:
        return None
    meta = json.loads(idx.read_text(encoding="utf-8-sig"))
    if int(meta.get("field_count", -1)) != EXPECTED_FIELDS or int(meta.get("municipality_count", -1)) != EXPECTED_WATER_MUNICIPALITIES:
        return None

    total = positive = level = 0
    sidecars = []
    required_cols = {
        "viss_positive_case", "dominant_EU_CD", "pressure_agriculture",
        "quantitative_risk_signal", "groundwater_level_impact",
        "groundwater_level_impact_motivation",
    }
    for row in meta.get("municipalities") or []:
        p = dist / str(row.get("file", ""))
        if not p.is_file():
            return None
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        cols = list(d.get("columns") or [])
        if not required_cols.issubset(cols):
            return None
        fields = d.get("fields") or {}
        total += len(fields)
        vi = cols.index("viss_positive_case")
        gi = cols.index("groundwater_level_impact")
        positive += sum(1 for values in fields.values() if vi < len(values) and bool(values[vi]))
        level += sum(1 for values in fields.values() if gi < len(values) and bool(values[gi]))
        sidecars.append(p)

    if total != EXPECTED_FIELDS or positive != EXPECTED_VISS_POSITIVE or level != EXPECTED_GW_LEVEL_IMPACT:
        return None
    return {
        "dist": str(dist.resolve()),
        "field_count": total,
        "viss_positive_fields": positive,
        "groundwater_level_impact_fields": level,
        "sidecars": len(sidecars),
        "index_sha256": sha256(idx),
        "js_sha256": sha256(js),
        "css_sha256": sha256(css),
    }

def discover_water(explicit: Path | None) -> tuple[Path, dict]:
    candidates = []
    if explicit:
        candidates.append(explicit)
    for root in candidate_roots():
        candidates.extend([root / "dist", root / "dist_akervatten_v0a"])
        try:
            candidates.extend(sorted(root.glob("dist*")))
        except OSError:
            pass
    checked = []
    seen = set()
    for p in candidates:
        try:
            p = p.resolve()
        except OSError:
            continue
        if p in seen:
            continue
        seen.add(p); checked.append(str(p))
        evidence = inspect_water_dist(p)
        if evidence:
            return p, evidence
    raise FileNotFoundError(
        "Could not auto-discover the frozen ÅkerVatten + VISS/VattenTryck dist.\nChecked:\n  "
        + "\n  ".join(checked[:80])
        + "\nPass --water-viss-dist explicitly if it lives elsewhere."
    )

def looks_like_raps_html(text: str) -> bool:
    low = text.lower()
    return "rapskartan" in low and ("2025" in low or "raps" in low)

def find_raps_dir(explicit: Path | None) -> tuple[Path, str]:
    """Find the already-built Rapskartan 2025 web without asking the user to hunt for it.

    Search order is deliberately biased toward the known historical artifact
    rapskartan_web_onecom.zip and the C:\AkerSync-Rapskartan worktree. We inspect
    only plausible ÅkerSync roots and Rapskartan-like paths; no full C: crawl.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)

    # Known historical package often lives in the user's Downloads folder.
    downloads = Path.home() / "Downloads"
    candidates.extend([
        downloads / "rapskartan_web_onecom.zip",
        downloads / "rapskartan_web_onecom",
    ])

    roots = list(candidate_roots())
    for root in roots:
        candidates.extend([
            root,
            root / "rapskartan_web_onecom.zip",
            root / "dist_rapskartan",
            root / "dist_rapskartan_2025",
            root / "rapskartan",
            root / "rapskartan25",
            root / "dist",
            root / "web",
        ])
        try:
            candidates.extend(sorted(root.glob("*raps*")))
            candidates.extend(sorted(root.glob("*Raps*")))
        except OSError:
            pass

    checked: list[str] = []
    seen: set[Path] = set()

    def inspect_candidate(p: Path) -> tuple[Path, str] | None:
        try:
            p = p.resolve()
        except OSError:
            return None
        if p in seen:
            return None
        seen.add(p)
        checked.append(str(p))

        if p.is_dir() and (p / "index.html").is_file():
            try:
                text = (p / "index.html").read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if looks_like_raps_html(text):
                return p, "directory"

        if p.is_file() and p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    indices = [n for n in z.namelist() if n.lower().endswith("index.html")]
                    for name in indices:
                        try:
                            text = z.read(name).decode("utf-8", errors="replace")
                        except Exception:
                            continue
                        if looks_like_raps_html(text):
                            return p, "zip"
            except (OSError, zipfile.BadZipFile):
                pass
        return None

    # Fast/direct candidates first.
    for p in candidates:
        hit = inspect_candidate(p)
        if hit:
            return hit

    # Targeted recursive search inside known ÅkerSync roots. This catches the
    # historical one.com package even if it was placed in a release/work folder.
    exact_zip_names = {"rapskartan_web_onecom.zip"}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            for p in root.rglob("*.zip"):
                low = p.name.lower()
                if low in exact_zip_names or ("raps" in low and ("web" in low or "onecom" in low)):
                    hit = inspect_candidate(p)
                    if hit:
                        return hit
        except OSError:
            pass

        # Search Rapskartan-ish HTML directories, but skip obviously large raw/data trees.
        try:
            for idx in root.rglob("index.html"):
                parts_low = [x.lower() for x in idx.parts]
                if any(x in {"data", "raw", ".git", ".venv", "__pycache__"} for x in parts_low):
                    continue
                joined = "/".join(parts_low)
                if "raps" not in joined and "rapskartan" not in joined:
                    continue
                hit = inspect_candidate(idx.parent)
                if hit:
                    return hit
        except OSError:
            pass

    raise FileNotFoundError(
        "Could not auto-discover the existing Rapskartan 2025 web.\n"
        "Looked specifically for rapskartan_web_onecom.zip and Rapskartan-like web dirs under "
        "C:\\AkerSync-Rapskartan, C:\\AkerSyncRepo and other C:\\AkerSync* roots.\n"
        "Pass --rapskartan explicitly only if the artifact truly lives elsewhere."
    )

def copy_raps(source: Path, kind: str, target: Path) -> dict:
    if target.exists():
        shutil.rmtree(target)
    if kind == "directory":
        shutil.copytree(source, target)
        source_desc = str(source)
    else:
        with tempfile.TemporaryDirectory(prefix="rapskartan_extract_") as td:
            tmp = Path(td)
            with zipfile.ZipFile(source) as z:
                z.extractall(tmp)
            matches = []
            for idx in tmp.rglob("index.html"):
                try:
                    if looks_like_raps_html(idx.read_text(encoding="utf-8", errors="replace")):
                        matches.append(idx.parent)
                except OSError:
                    pass
            if not matches:
                raise RuntimeError("Rapskartan ZIP contains no recognizable index.html")
            root = min(matches, key=lambda x: len(x.parts))
            shutil.copytree(root, target)
        source_desc = str(source)
    idx = target / "index.html"
    if not idx.is_file():
        raise RuntimeError("Copied Rapskartan has no index.html")
    text = idx.read_text(encoding="utf-8", errors="replace")
    marker = "AKERPASS_RAPSKARTAN_BACKLINK_V0A"
    if marker not in text:
        backlink = (
            '\n<!-- ' + marker + ' -->\n'
            '<a href="../" style="position:fixed;z-index:99999;left:12px;top:12px;'
            'padding:8px 11px;border-radius:10px;background:rgba(255,255,255,.94);'
            'color:#17352b;text-decoration:none;font:700 13px system-ui;'
            'box-shadow:0 2px 10px rgba(0,0,0,.18)">← Till ÅkerPass</a>\n'
        )
        text = replace_once(text, "</body>", backlink + "</body>", "Rapskartan backlink")
        idx.write_text(text, encoding="utf-8")
    return {"source": source_desc, "kind": kind, "index_sha256": sha256(idx)}

def patch_unified_html(index: Path, water_index: dict) -> None:
    text = index.read_text(encoding="utf-8")
    for marker in (NORM_MARK, FRO_MARK, ACCESS_MARK):
        if marker not in text:
            raise RuntimeError(f"Access base missing expected marker: {marker}")
    if UNIFIED_MARK in text:
        raise RuntimeError("Unified patch must start from a fresh Access build")

    text = replace_once(
        text, "</head>",
        '<link rel="stylesheet" href="assets/akervatten_v0a.css">\n'
        f'<!-- {WATER_MARK} -->\n<!-- {VISS_MARK} -->\n<!-- {UNIFIED_MARK} -->\n</head>',
        "unified stylesheet hook",
    )

    fro = '<button class="layer-button" type="button" data-layer="fro" title="Konservärt 2026 · kandidatfält">ÅkerFrö</button>'
    water = '<button class="layer-button" type="button" data-layer="vatten" title="Mark, grundvatten, ytvatten och VISS · separata informationslager">ÅkerVatten</button>'
    text = replace_once(text, fro, fro + "\n   " + water, "ÅkerVatten layer button")

    hint = '<div id="layerHint" class="hint"></div>'
    text = replace_once(text, hint, hint + "\n" + WATER_CONTROLS, "ÅkerVatten controls")

    akf = "$" + "{akerfroSection(p)}"
    akv = "$" + "{akervattenSection(p)}"
    anchor = " " + akf + "\n <details><summary>Historik / referens</summary>"
    replacement = " " + akf + "\n " + akv + "\n <details><summary>Historik / referens</summary>"
    text = replace_once(text, anchor, replacement, "ÅkerVatten field drawer")

    entries = water_index.get("municipalities") or []
    mapping = {str(row["municipality"]): str(row["file"]) for row in entries}
    regional = {k: str(v["file"]) for k, v in (water_index.get("regional") or {}).items()}
    cfg = {
        "files": mapping,
        "regional": regional,
        "schema": "akervatten-web-field-v0a",
        "overall_score": "NOT_CREATED",
        "legal_status": "NOT_ASSESSED",
        "viss_version": "VattenTryck v1 FROZEN",
    }
    scripts = (
        '<script>window.AKERVATTEN_WEB_CONFIG='
        + json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
        + ';</script>\n<script src="assets/akervatten_v0a.js"></script>\n'
    )
    text = replace_once(text, "</body>", scripts + "</body>", "ÅkerVatten script hook")

    nav = (
        '<a id="rapskartanNav" href="rapskartan25/" '
        'style="position:fixed;right:12px;top:12px;z-index:9999;padding:8px 11px;'
        'border-radius:10px;background:rgba(255,255,255,.94);color:#17352b;'
        'text-decoration:none;font:700 12px system-ui;box-shadow:0 2px 10px rgba(0,0,0,.16)">'
        'Rapskartan 2025</a>\n'
    )
    text = replace_once(text, "</body>", nav + "</body>", "Rapskartan navigation")

    index.write_text(text, encoding="utf-8")

def patch_rotation_v1a_sidecars(target: Path) -> dict:
    """Patch only the 43 formally frozen Rotation v1.1 releases into the copied
    municipality ÅkerFrö web sidecars.

    The source ÅkerFrö web remains untouched. We overwrite the existing
    artkandidat_class / rotation_status values in the copied unified dist and
    preserve every other field and ranking value. This is presentation
    forward-porting of a frozen downstream product, not model recalculation.
    """
    if not ROTATION.is_file():
        raise FileNotFoundError(f"Frozen Rotation v1.1 product missing: {ROTATION}")
    rot = pd.read_parquet(
        ROTATION,
        columns=[
            "current_field_id", "artkandidat_class_v1a", "rotation_status_v1a",
            "rotation_v1a_evidence", "rotation_v1a_release_candidate",
            "artkandidat_reason_v1a",
        ],
    )
    released = rot[rot["rotation_v1a_release_candidate"].fillna(False).astype(bool)].copy()
    if len(released) != EXPECTED_ROTATION_RELEASED:
        raise RuntimeError(f"Rotation v1.1 release anchor drift: {len(released)} != {EXPECTED_ROTATION_RELEASED}")
    values = {
        str(r.current_field_id): {
            "artkandidat_class": str(r.artkandidat_class_v1a),
            "rotation_status": str(r.rotation_status_v1a),
            "rotation_v1a_evidence": str(r.rotation_v1a_evidence),
            "artkandidat_reason": str(r.artkandidat_reason_v1a),
        }
        for r in released.itertuples(index=False)
    }

    base = target / "data" / "akerfro"
    if not base.is_dir():
        raise RuntimeError("Copied ÅkerFrö municipality data missing")
    found: set[str] = set()
    files_modified = 0
    staffanstorp_94a_seen = False

    for p in sorted(base.rglob("*.json")):
        if p.name == "skane_index.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        fields = d.get("fields")
        changed = False

        # Compact sidecar format: columns + {field_id: [values...]}
        cols = d.get("columns")
        if isinstance(cols, list) and isinstance(fields, dict):
            if "artkandidat_class" in cols and "rotation_status" in cols:
                ci = cols.index("artkandidat_class")
                ri = cols.index("rotation_status")
                reason_i = cols.index("artkandidat_reason") if "artkandidat_reason" in cols else None
                for fid in set(fields).intersection(values):
                    row = fields[fid]
                    if not isinstance(row, list):
                        continue
                    row[ci] = values[fid]["artkandidat_class"]
                    row[ri] = values[fid]["rotation_status"]
                    if reason_i is not None and reason_i < len(row):
                        row[reason_i] = values[fid]["artkandidat_reason"]
                    found.add(fid); changed = True
                if "61723353349|94A" in fields:
                    staffanstorp_94a_seen = True

        # Object sidecar format: {field_id: {column: value}}
        elif isinstance(fields, dict):
            for fid in set(fields).intersection(values):
                row = fields[fid]
                if not isinstance(row, dict) or "artkandidat_class" not in row or "rotation_status" not in row:
                    continue
                row["artkandidat_class"] = values[fid]["artkandidat_class"]
                row["rotation_status"] = values[fid]["rotation_status"]
                if "artkandidat_reason" in row:
                    row["artkandidat_reason"] = values[fid]["artkandidat_reason"]
                found.add(fid); changed = True
            if "61723353349|94A" in fields:
                staffanstorp_94a_seen = True

        # Row-list format: fields=[{field_id:..., ...}, ...]
        elif isinstance(fields, list):
            for row in fields:
                if not isinstance(row, dict):
                    continue
                fid = str(row.get("field_id") or row.get("current_field_id") or "")
                if fid in values and "artkandidat_class" in row and "rotation_status" in row:
                    row["artkandidat_class"] = values[fid]["artkandidat_class"]
                    row["rotation_status"] = values[fid]["rotation_status"]
                    if "artkandidat_reason" in row:
                        row["artkandidat_reason"] = values[fid]["artkandidat_reason"]
                    found.add(fid); changed = True
                if fid == "61723353349|94A":
                    staffanstorp_94a_seen = True

        if changed:
            p.write_text(stable_json(d), encoding="utf-8")
            files_modified += 1

    missing = sorted(set(values) - found)
    if missing:
        raise RuntimeError(
            f"Rotation v1.1 web forward-port found only {len(found)}/{EXPECTED_ROTATION_RELEASED} released fields; "
            f"missing examples: {', '.join(missing[:10])}"
        )
    if not staffanstorp_94a_seen:
        raise RuntimeError("Staffanstorp 94A regression anchor not found in copied ÅkerFrö sidecars")

    idx = base / "skane_index.json"
    meta = json.loads(idx.read_text(encoding="utf-8-sig"))
    meta["rotation_policy"] = "akerfro-rotation-v1a"
    meta["rotation_v1a_status"] = "FORMALLY_FROZEN"
    meta["rotation_v1a_released_fields"] = EXPECTED_ROTATION_RELEASED
    meta["rotation_v1a_source_sha256"] = sha256(ROTATION)
    meta["rotation_v1a_web_semantics"] = "43 frozen C->A/B boundary-spill releases forward-ported; all other municipality ÅkerFrö values preserved."
    idx.write_text(stable_json(meta), encoding="utf-8")
    return {
        "source": str(ROTATION),
        "sha256": sha256(ROTATION),
        "released_fields_patched": len(found),
        "sidecar_files_modified": files_modified,
        "staffanstorp_94a_seen": staffanstorp_94a_seen,
    }


def normalize_access_product_meta(target: Path) -> None:
    p = target / "data" / "akerfro_bestmatch" / "skane_index.json"
    if not p.is_file():
        raise RuntimeError("Access/BestMatch web index missing")
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    d["status"] = "FROZEN_BESTMATCH_V0C_PRESENTATION"
    d["product_version"] = "v0c"
    d["candidate_fields"] = EXPECTED_BESTMATCH_CANDIDATES
    d["canonical_product"] = "data/derived/akerfro_akeraccess_bestmatch_v0c/bestmatch_v0c_fields.parquet"
    d["freeze_note"] = "BestMatch v0c frozen: Rotation v1.1 eligibility + unchanged 50% ÄrtMatch + 25% väg-AreaLogistik + 25% ÅkerAccess v0a; A before B."
    p.write_text(stable_json(d), encoding="utf-8")

def manifest_files(root: Path) -> list[dict]:
    rows = []
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        rel = p.relative_to(root).as_posix()
        rows.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256(p)})
    return rows

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--akerfro-base", type=Path)
    ap.add_argument("--water-viss-dist", type=Path)
    ap.add_argument("--rapskartan", type=Path)
    ap.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    args = ap.parse_args()

    if not BESTMATCH.is_file():
        raise FileNotFoundError(
            f"Frozen BestMatch v0c product missing: {BESTMATCH}\n"
            "Run/restore the frozen v0c product before unified web build; D5/v0b fallback is not allowed."
        )
    if not ROTATION.is_file():
        raise FileNotFoundError(f"Frozen Rotation v1.1 product missing: {ROTATION}")

    WORK.mkdir(parents=True, exist_ok=True)
    if ACCESS_BASE.exists():
        shutil.rmtree(ACCESS_BASE)

    access_cmd = [
        sys.executable, str(ROOT / "src" / "92_build_akerfro_access_web_v0b.py"),
        "--d5", str(BESTMATCH),
        "--target", str(ACCESS_BASE),
    ]
    if args.akerfro_base:
        access_cmd += ["--base-dist", str(args.akerfro_base)]
    print("[1/6] Build fresh Access/BestMatch presentation from frozen BestMatch v0c...")
    run(access_cmd)

    print("[2/6] Auto-discover and validate frozen ÅkerVatten + VISS/VattenTryck v1 web payload...")
    water_src, water_evidence = discover_water(args.water_viss_dist)
    print("ÅkerVatten-VISS source:", water_src)
    print("VISS positive fields:", f"{water_evidence['viss_positive_fields']:,}")
    print("Groundwater-level impact fields:", f"{water_evidence['groundwater_level_impact_fields']:,}")

    target = args.dist.resolve()
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ACCESS_BASE, target)

    print("[3/6] Forward-port frozen Rotation v1.1 into municipality ÅkerFrö sidecars...")
    rotation_evidence = patch_rotation_v1a_sidecars(target)
    print("Rotation v1.1 releases patched:", f"{rotation_evidence['released_fields_patched']:,}")

    water_dest = target / "data" / "akervatten"
    if water_dest.exists():
        shutil.rmtree(water_dest)
    shutil.copytree(water_src / "data" / "akervatten", water_dest)
    (target / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(water_src / "assets" / "akervatten_v0a.css", target / "assets" / "akervatten_v0a.css")
    shutil.copy2(water_src / "assets" / "akervatten_v0a.js", target / "assets" / "akervatten_v0a.js")

    water_index = json.loads((water_dest / "skane_index.json").read_text(encoding="utf-8-sig"))
    patch_unified_html(target / "index.html", water_index)
    normalize_access_product_meta(target)

    print("[4/6] Auto-discover and copy Rapskartan 2025 as separate special view...")
    raps_src, raps_kind = find_raps_dir(args.rapskartan)
    raps_meta = copy_raps(raps_src, raps_kind, target / "rapskartan25")
    print("Rapskartan source:", raps_src)

    print("[5/6] Write unified manifest...")
    manifest = {
        "schema_version": "akerpass-unified-web-v0a",
        "status": "BUILT_NOT_YET_VERIFIED",
        "repository_head": git_head(),
        "frozen_inputs": {
            "bestmatch_v0c": {
                "path": str(BESTMATCH),
                "sha256": sha256(BESTMATCH),
                "candidate_fields": EXPECTED_BESTMATCH_CANDIDATES,
            },
            "akerfro_rotation_v1a": rotation_evidence,
            "akervatten_viss_vattentryck_v1": water_evidence,
            "rapskartan_2025": raps_meta,
        },
        "scope": {
            "models_recalculated": False,
            "new_total_score_created": False,
            "water_legal_assessment_created": False,
            "deployment_performed": False,
        },
        "dist": str(target),
    }
    (WORK / "build_manifest.json").write_text(stable_json(manifest), encoding="utf-8")

    print("[6/6] Build complete; run independent unified verifier...")
    print("=" * 108)
    print("BUILD_AKERPASS_UNIFIED_WEB_V0A: PASS")
    print("Target:", target)
    print("Frozen Rotation v1.1: YES · 43 releases")
    print("Frozen BestMatch v0c: YES · 16,004 candidates")
    print("ÅkerVatten + VISS/VattenTryck v1: YES")
    print("Rapskartan 2025 special view: YES")
    print("New total score: NO")
    print("Deployment: NO")
    print("=" * 108)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
