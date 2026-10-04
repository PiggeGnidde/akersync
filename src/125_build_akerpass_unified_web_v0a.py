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
ROTATION_PRIORITY_MARK = "AKERFRO_ROTATION_V1A_PRIORITY_UI"

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

def _norm_text_id(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if "|" not in s and s.count(":") == 1:
        left, right = s.split(":", 1)
        if left.strip().isdigit() and right.strip():
            s = left.strip() + "|" + right.strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    return s


def _fid_from_mapping(obj: dict) -> str:
    """Best-effort current-field id from the web-sidecar record itself."""
    for key in ("field_id", "current_field_id", "fid"):
        if key in obj and obj.get(key) not in (None, ""):
            s = _norm_text_id(obj.get(key))
            if "|" in s:
                return s

    block = ""
    skifte = ""
    for key in (
        "blockid", "block_id", "block", "current_block_id",
        "jordbruksblock", "blockId", "BLOCKID",
    ):
        if key in obj and obj.get(key) not in (None, ""):
            block = _norm_text_id(obj.get(key))
            break
    for key in (
        "skiftesbeteckning", "skifte", "skifte_id", "current_skiftesbeteckning",
        "skiftesbeteckn", "skiftebeteckning", "SKIFTESBETECKNING",
    ):
        if key in obj and obj.get(key) not in (None, ""):
            skifte = _norm_text_id(obj.get(key))
            break
    return f"{block}|{skifte}" if block and skifte else ""


def _patch_record_mapping(obj: dict, values: dict[str, dict], found: set[str]) -> bool:
    """Patch one row/property dict if it identifies a frozen release field."""
    fid = _fid_from_mapping(obj)
    if fid not in values:
        return False

    changed = False
    v = values[fid]

    # Common direct fields.
    if "artkandidat_class" in obj:
        obj["artkandidat_class"] = v["artkandidat_class"]; changed = True
    if "rotation_status" in obj:
        obj["rotation_status"] = v["rotation_status"]; changed = True
    if "artkandidat_reason" in obj:
        obj["artkandidat_reason"] = v["artkandidat_reason"]; changed = True

    # Some web payloads group ÅkerFrö values in a nested object.
    for key in ("akerfro", "åkerfro", "fro", "artkandidat"):
        nested = obj.get(key)
        if isinstance(nested, dict):
            if "artkandidat_class" in nested:
                nested["artkandidat_class"] = v["artkandidat_class"]; changed = True
            if "rotation_status" in nested:
                nested["rotation_status"] = v["rotation_status"]; changed = True
            if "artkandidat_reason" in nested:
                nested["artkandidat_reason"] = v["artkandidat_reason"]; changed = True

    if changed:
        found.add(fid)
    return changed


def _dict_encode(container: dict, dict_name: str, value: str):
    """Encode a text value using the sidecar's own dictionary, extending it if needed."""
    dictionaries = container.get("dictionaries")
    if not isinstance(dictionaries, dict):
        return value
    values = dictionaries.get(dict_name)
    if not isinstance(values, list):
        return value
    if value not in values:
        values.append(value)
    return values.index(value)


def _dict_decode(container: dict, dict_name: str, value):
    dictionaries = container.get("dictionaries")
    if not isinstance(dictionaries, dict):
        return value
    values = dictionaries.get(dict_name)
    if not isinstance(values, list):
        return value
    try:
        i = int(value)
    except Exception:
        return value
    return values[i] if 0 <= i < len(values) else value


def _refresh_class_counts(container: dict) -> None:
    """Recompute municipality class_counts after compact-row edits."""
    if not isinstance(container.get("class_counts"), dict):
        return
    cols = container.get("columns")
    rows = container.get("fields")
    if not isinstance(cols, list) or not isinstance(rows, (dict, list)):
        return
    class_col = "artkandidat_class" if "artkandidat_class" in cols else ("class" if "class" in cols else None)
    if class_col is None:
        return
    ci = cols.index(class_col)
    counts: dict[str, int] = {}
    iterator = rows.values() if isinstance(rows, dict) else rows
    for row in iterator:
        if not isinstance(row, list) or ci >= len(row):
            continue
        raw = row[ci]
        label = _dict_decode(container, "class", raw) if class_col == "class" else raw
        label = str(label)
        counts[label] = counts.get(label, 0) + 1
    container["class_counts"] = counts


def _patch_column_table(container: dict, values: dict[str, dict], found: set[str]) -> bool:
    """Patch compact dictionary-coded or raw column tables."""
    cols = container.get("columns")
    if not isinstance(cols, list):
        return False

    class_col = (
        "artkandidat_class" if "artkandidat_class" in cols
        else ("class" if "class" in cols else None)
    )
    rot_col = "rotation_status" if "rotation_status" in cols else None
    if class_col is None or rot_col is None:
        return False

    fid_col = next((x for x in ("field_id", "current_field_id", "fid") if x in cols), None)
    block_col = next((x for x in (
        "blockid", "block_id", "block", "current_block_id", "jordbruksblock"
    ) if x in cols), None)
    skifte_col = next((x for x in (
        "skiftesbeteckning", "skifte", "skifte_id", "current_skiftesbeteckning"
    ) if x in cols), None)

    ci, ri = cols.index(class_col), cols.index(rot_col)
    reason_i = cols.index("artkandidat_reason") if "artkandidat_reason" in cols else None
    changed = False

    for data_key in ("rows", "data", "records", "fields"):
        rows = container.get(data_key)
        if isinstance(rows, dict):
            iterator = rows.items()
        elif isinstance(rows, list):
            iterator = enumerate(rows)
        else:
            continue

        for row_key, row in iterator:
            if not isinstance(row, list):
                continue

            fid = ""
            if fid_col:
                fi = cols.index(fid_col)
                if fi < len(row):
                    fid = _norm_text_id(row[fi])
            elif block_col and skifte_col:
                bi, si = cols.index(block_col), cols.index(skifte_col)
                if bi < len(row) and si < len(row):
                    fid = f"{_norm_text_id(row[bi])}|{_norm_text_id(row[si])}"
            if not fid and isinstance(rows, dict):
                fid = _norm_text_id(row_key)

            if fid not in values:
                continue

            v = values[fid]
            if ci < len(row):
                row[ci] = (
                    _dict_encode(container, "class", v["artkandidat_class"])
                    if class_col == "class"
                    else v["artkandidat_class"]
                )
            if ri < len(row):
                row[ri] = _dict_encode(container, "rotation_status", v["rotation_status"])
            if reason_i is not None and reason_i < len(row):
                row[reason_i] = v["artkandidat_reason"]

            found.add(fid)
            changed = True

    if changed:
        _refresh_class_counts(container)
    return changed


def _patch_json_tree(node, values: dict[str, dict], found: set[str]) -> bool:
    """Recursively patch row-like records, GeoJSON properties and compact tables."""
    changed = False
    if isinstance(node, dict):
        changed |= _patch_column_table(node, values, found)
        changed |= _patch_record_mapping(node, values, found)

        # Dictionary keyed directly by field id.
        for key, child in list(node.items()):
            key_s = _norm_text_id(key)
            if key_s in values:
                v = values[key_s]
                if isinstance(child, dict):
                    local = False
                    if "artkandidat_class" in child:
                        child["artkandidat_class"] = v["artkandidat_class"]; local = True
                    if "rotation_status" in child:
                        child["rotation_status"] = v["rotation_status"]; local = True
                    if "artkandidat_reason" in child:
                        child["artkandidat_reason"] = v["artkandidat_reason"]; local = True
                    if local:
                        found.add(key_s); changed = True
                elif isinstance(child, list):
                    # Handled when the parent also carries a columns array.
                    pass

        for child in node.values():
            if isinstance(child, (dict, list)):
                changed |= _patch_json_tree(child, values, found)

    elif isinstance(node, list):
        for child in node:
            if isinstance(child, (dict, list)):
                changed |= _patch_json_tree(child, values, found)
    return changed


def _contains_field_identity(node, fid: str) -> bool:
    """Read-only recursive identity search used for the 94A regression anchor."""
    block, skifte = fid.split("|", 1)
    if isinstance(node, dict):
        if _fid_from_mapping(node) == fid:
            return True
        if fid in node:
            return True
        return any(_contains_field_identity(v, fid) for v in node.values() if isinstance(v, (dict, list)))
    if isinstance(node, list):
        return any(_contains_field_identity(v, fid) for v in node if isinstance(v, (dict, list)))
    return False


def patch_rotation_v1a_sidecars(target: Path) -> dict:
    """Forward-port the 43 formally frozen Rotation v1.1 releases.

    The ÅkerFrö web payload has existed in more than one JSON representation.
    This routine therefore identifies current fields semantically rather than
    assuming one particular sidecar shape.
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
    json_files = 0

    for p in sorted(base.rglob("*.json")):
        if p.name == "skane_index.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        json_files += 1

        if _contains_field_identity(d, "61723353349|94A"):
            staffanstorp_94a_seen = True

        changed = _patch_json_tree(d, values, found)
        if changed:
            p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            files_modified += 1

    missing = sorted(set(values) - found)
    if missing:
        raise RuntimeError(
            f"Rotation v1.1 web forward-port found only {len(found)}/{EXPECTED_ROTATION_RELEASED} released fields "
            f"across {json_files} ÅkerFrö JSON sidecars; missing examples: {', '.join(missing[:10])}. "
            "This means the base web uses an additional field encoding that must be handled explicitly."
        )
    if not staffanstorp_94a_seen:
        raise RuntimeError("Staffanstorp 94A regression anchor not found in copied ÅkerFrö sidecars")

    idx = base / "skane_index.json"
    meta = json.loads(idx.read_text(encoding="utf-8-sig"))
    meta["rotation_policy"] = "akerfro-rotation-v1a"
    meta["rotation_v1a_status"] = "FORMALLY_FROZEN"
    meta["rotation_v1a_released_fields"] = EXPECTED_ROTATION_RELEASED
    meta["rotation_v1a_source_sha256"] = sha256(ROTATION)
    meta["rotation_v1a_web_semantics"] = (
        "43 frozen C->A/B boundary-spill releases forward-ported; "
        "all other municipality ÅkerFrö values preserved."
    )
    idx.write_text(stable_json(meta), encoding="utf-8")
    return {
        "source": str(ROTATION),
        "sha256": sha256(ROTATION),
        "released_fields_patched": len(found),
        "sidecar_files_modified": files_modified,
        "json_sidecars_scanned": json_files,
        "staffanstorp_94a_seen": staffanstorp_94a_seen,
    }


def install_rotation_v1a_priority_ui(target: Path) -> dict:
    """Replace stale frozen-v0a priority text only for the 43 v1.1 releases.

    The old C10 priority stays untouched in source data for provenance. A tiny
    presentation map tells the browser what the current downstream status is:
    BestMatch v0c rank for the 37 D5 candidates, or explicit D0 <1 ha exclusion
    for the remaining six.
    """
    if not ROTATION.is_file() or not BESTMATCH.is_file():
        raise FileNotFoundError("Rotation v1.1 / BestMatch v0c frozen products required")

    rot = pd.read_parquet(
        ROTATION,
        columns=["current_field_id","rotation_v1a_release_candidate"],
    )
    rel = rot[rot["rotation_v1a_release_candidate"].fillna(False).astype(bool)].copy()
    if len(rel) != EXPECTED_ROTATION_RELEASED:
        raise RuntimeError("Rotation v1.1 release anchor drift while building priority UI")

    bm = pd.read_parquet(BESTMATCH, columns=["field_id","bestmatch_v0c_rank"]).copy()
    bm["field_id"] = bm["field_id"].astype(str)
    ranks = {
        str(r.field_id): int(r.bestmatch_v0c_rank)
        for r in bm.itertuples(index=False)
        if pd.notna(r.bestmatch_v0c_rank)
    }

    mapping = {}
    in_bestmatch = 0
    outside = 0
    for fid in rel["current_field_id"].astype(str):
        if fid in ranks:
            rank = int(ranks[fid])
            mapping[fid] = {
                "status": "BESTMATCH_V0C",
                "rank": rank,
                "label": f"BestMatch v0c #{rank:,}".replace(",", " "),
            }
            in_bestmatch += 1
        else:
            mapping[fid] = {
                "status": "D0_AREA_LT_1_HA",
                "rank": None,
                "label": "Ej i BestMatch · <1 ha",
            }
            outside += 1

    if in_bestmatch != 37 or outside != 6:
        raise RuntimeError(
            f"Rotation priority UI anchors drift: BestMatch={in_bestmatch}, outside={outside}"
        )

    data_path = target / "data" / "akerfro" / "rotation_v1a_priority_override.json"
    payload = {
        "schema_version": "akerfro-rotation-v1a-priority-ui-v1",
        "status": "PRESENTATION_ONLY_FROZEN_INPUTS",
        "rotation_release_fields": EXPECTED_ROTATION_RELEASED,
        "bestmatch_v0c_fields": in_bestmatch,
        "d0_area_lt_1ha_fields": outside,
        "semantics": (
            "For Rotation v1.1 boundary-spill releases only, replace stale v0a/C10 "
            "priority text in the municipality drawer with frozen BestMatch v0c rank; "
            "fields excluded by frozen D0 area>=1ha show explicit exclusion text."
        ),
        "fields": mapping,
    }
    data_path.write_text(stable_json(payload), encoding="utf-8")

    js_path = target / "assets" / "akerfro_rotation_v1a_priority_ui.js"
    js = r'''/* AKERFRO_ROTATION_V1A_PRIORITY_UI */
(function(){
"use strict";
const FILE="data/akerfro/rotation_v1a_priority_override.json";
let mapping=null;
function currentFieldId(){
  const q=new URLSearchParams(location.search);
  const block=q.get("block"),skifte=q.get("skifte");
  return block&&skifte ? String(block)+"|"+String(skifte) : "";
}
function replaceText(){
  if(!mapping)return;
  const fid=currentFieldId(),item=mapping[fid];
  if(!item)return;
  const root=document.body;if(!root)return;
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  const nodes=[];
  while(walker.nextNode())nodes.push(walker.currentNode);
  nodes.forEach(function(n){
    const parent=n.parentElement;
    if(!parent||["SCRIPT","STYLE"].includes(parent.tagName))return;
    const s=n.nodeValue||"";
    if(!/prioritet\s*#/i.test(s))return;
    n.nodeValue=s.replace(/prioritet\s*#\s*[\d\s\u00a0]+/ig,item.label);
  });
}
function boot(){
  fetch(FILE,{cache:"no-cache"}).then(function(r){
    if(!r.ok)throw new Error("Rotation v1.1 priority UI HTTP "+r.status);
    return r.json();
  }).then(function(d){
    mapping=(d&&d.fields)||{};
    replaceText();
    const obs=new MutationObserver(function(){replaceText()});
    obs.observe(document.body,{subtree:true,childList:true,characterData:true});
    window.addEventListener("popstate",replaceText);
  }).catch(function(e){console.error(e)});
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);
else boot();
})();
'''
    js_path.write_text(js, encoding="utf-8")

    index = target / "index.html"
    text = index.read_text(encoding="utf-8")
    if ROTATION_PRIORITY_MARK in text:
        raise RuntimeError("Rotation v1.1 priority UI already installed")
    hook = (
        f'<!-- {ROTATION_PRIORITY_MARK} -->\n'
        '<script src="assets/akerfro_rotation_v1a_priority_ui.js"></script>\n'
    )
    text = replace_once(text, "</body>", hook + "</body>", "Rotation v1.1 priority UI hook")
    index.write_text(text, encoding="utf-8")

    return {
        "fields": len(mapping),
        "bestmatch_v0c_fields": in_bestmatch,
        "d0_area_lt_1ha_fields": outside,
        "data": "data/akerfro/rotation_v1a_priority_override.json",
        "js": "assets/akerfro_rotation_v1a_priority_ui.js",
        "staffanstorp_2a_rank": mapping["61723351559|2A"]["rank"],
        "staffanstorp_2b_rank": mapping["61723351559|2B"]["rank"],
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
    priority_ui = install_rotation_v1a_priority_ui(target)
    print(
        "Rotation v1.1 priority UI:",
        f"{priority_ui['bestmatch_v0c_fields']} BestMatch ranks · "
        f"{priority_ui['d0_area_lt_1ha_fields']} explicit <1 ha exclusions",
    )

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
            "akerfro_rotation_v1a_priority_ui": priority_ui,
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
