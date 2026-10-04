#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent verifier for ÅkerPass Unified Preview Web v0a."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "akerpass_unified_web_v0a"
DEFAULT_DIST = ROOT / "dist_akerpass_unified_v0a"

EXPECTED_FIELDS = 128_636
EXPECTED_MUNICIPALITIES = 33
EXPECTED_VISS_POSITIVE = 16_626
EXPECTED_GW_LEVEL_IMPACT = 5_495
EXPECTED_ROTATION_RELEASED = 43
EXPECTED_BESTMATCH_CANDIDATES = 16_004
EXPECTED_SCREENING_UNION = 5_000
ROTATION = ROOT / "data" / "derived" / "akerfro_rotation_v1a" / "akerfro_rotation_v1a_fields.parquet"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_json(path: Path):
    if not path.is_file():
        raise RuntimeError(f"Missing JSON: {path}")
    def reject_constant(value: str):
        raise RuntimeError(f"Browser-invalid JSON constant {value} in {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)

def local_refs(html: str) -> list[str]:
    refs = []
    for attr in ("src", "href"):
        for value in re.findall(rf'\b{attr}=["\']([^"\']+)["\']', html, flags=re.I):
            v = value.strip()
            if not v or v.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
                continue
            parts = urlsplit(v)
            if parts.scheme or parts.netloc:
                continue
            refs.append(parts.path)
    return refs

def verify_local_refs(root: Path, html_path: Path, problems: list[str]) -> None:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    for ref in local_refs(html):
        if not ref:
            continue
        p = (html_path.parent / ref).resolve()
        try:
            p.relative_to(root.resolve())
        except ValueError:
            problems.append(f"LOCAL REF ESCAPES DIST: {html_path} -> {ref}")
            continue
        if ref.endswith("/") and (p / "index.html").is_file():
            continue
        if p.is_dir() and (p / "index.html").is_file():
            continue
        if not p.exists():
            problems.append(f"BROKEN LOCAL REF: {html_path.relative_to(root)} -> {ref}")

def scan_forbidden_text(dist: Path, problems: list[str]) -> None:
    suffixes = {".html", ".js", ".css", ".json", ".txt", ".md"}
    secret_patterns = [
        re.compile(r'(?i)\b(viss[_-]?api[_-]?key|api[_-]?key|secret|password)\b\s*[:=]\s*["\'][^"\']{8,}["\']'),
        re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._-]{16,}'),
    ]
    for p in dist.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        if p.stat().st_size > 20 * 1024 * 1024:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r'(?i)[A-Z]:\\(?:Users|AkerSync|Temp|tmp)\\', text):
            problems.append(f"LOCAL WINDOWS PATH LEAK: {p.relative_to(dist)}")
        for pattern in secret_patterns:
            if pattern.search(text):
                problems.append(f"POSSIBLE SECRET IN DIST: {p.relative_to(dist)}")
                break

def verify_water(dist: Path, problems: list[str]) -> dict:
    base = dist / "data" / "akervatten"
    idx = load_json(base / "skane_index.json")
    if int(idx.get("field_count", -1)) != EXPECTED_FIELDS:
        problems.append("ÅKERVATTEN INDEX FIELD COUNT MISMATCH")
    entries = idx.get("municipalities") or []
    if len(entries) != EXPECTED_MUNICIPALITIES:
        problems.append("ÅKERVATTEN MUNICIPALITY COUNT MISMATCH")
    if idx.get("overall_score") != "NOT_CREATED":
        problems.append("ÅKERVATTEN OVERALL SCORE WAS CREATED")
    if idx.get("legal_status") != "NOT_ASSESSED":
        problems.append("ÅKERVATTEN LEGAL STATUS CHANGED")

    required = {
        "viss_positive_case", "viss_gw_relation_count", "dominant_EU_CD",
        "pressure_agriculture", "pressure_municipal", "pressure_industry",
        "pressure_generic", "pressure_other", "quantitative_risk_signal",
        "groundwater_level_impact", "groundwater_level_impact_motivation",
    }
    total = positive = level = 0
    ids = set()
    for row in entries:
        p = dist / str(row.get("file", ""))
        if not p.is_file():
            problems.append(f"MISSING WATER SIDECAR {p}")
            continue
        d = load_json(p)
        if d.get("schema_version") != "akervatten-web-field-v0a":
            problems.append(f"WATER SIDECAR SCHEMA MISMATCH {p.name}")
        cols = list(d.get("columns") or [])
        missing = sorted(required - set(cols))
        if missing:
            problems.append(f"WATER SIDECAR {p.name} MISSING VISS COLS: {', '.join(missing)}")
            continue
        fields = d.get("fields") or {}
        total += len(fields)
        overlap = ids.intersection(fields)
        if overlap:
            problems.append(f"DUPLICATE WATER FIELD IDS IN {p.name}")
        ids.update(fields)
        vi = cols.index("viss_positive_case")
        gi = cols.index("groundwater_level_impact")
        positive += sum(1 for values in fields.values() if vi < len(values) and bool(values[vi]))
        level += sum(1 for values in fields.values() if gi < len(values) and bool(values[gi]))

    if total != EXPECTED_FIELDS:
        problems.append(f"WATER SIDECAR TOTAL {total} != {EXPECTED_FIELDS}")
    if positive != EXPECTED_VISS_POSITIVE:
        problems.append(f"VISS POSITIVE FIELD COUNT {positive} != {EXPECTED_VISS_POSITIVE}")
    if level != EXPECTED_GW_LEVEL_IMPACT:
        problems.append(f"GW LEVEL IMPACT FIELD COUNT {level} != {EXPECTED_GW_LEVEL_IMPACT}")

    for name in ("groundwater_history.geojson", "surfacewater_history.geojson", "large_groundwater.geojson"):
        if not (base / name).is_file():
            problems.append(f"MISSING ÅKERVATTEN REGIONAL LAYER {name}")

    js = dist / "assets" / "akervatten_v0a.js"
    css = dist / "assets" / "akervatten_v0a.css"
    if not js.is_file() or not css.is_file():
        problems.append("ÅKERVATTEN ASSETS MISSING")
    else:
        jt = js.read_text(encoding="utf-8", errors="replace")
        for token in (
            "AKERVATTEN_WEB_UI_V0A", "AKERVATTEN_VISS_UI_V0A",
            "groundwater_level_impact", "VISS", "currentWaterLayer",
            "Vattenrätt: ej bedömd",
        ):
            if token not in jt:
                problems.append(f"ÅKERVATTEN JS MISSING TOKEN {token}")

    return {"field_count": total, "viss_positive_fields": positive, "groundwater_level_impact_fields": level}

def verify_access(dist: Path, problems: list[str]) -> dict:
    base = dist / "data" / "akerfro_bestmatch"
    p = base / "skane_index.json"
    d = load_json(p)
    if d.get("status") != "FROZEN_BESTMATCH_V0C_PRESENTATION":
        problems.append("BESTMATCH WEB META NOT MARKED FROZEN V0C PRESENTATION")
    if d.get("product_version") != "v0c":
        problems.append("BESTMATCH WEB META PRODUCT VERSION IS NOT v0c")
    canonical = str(d.get("canonical_product", ""))
    if "bestmatch_v0c_fields.parquet" not in canonical:
        problems.append("BESTMATCH v0c CANONICAL PRODUCT METADATA MISSING")
    if int(d.get("candidate_fields", 0)) != EXPECTED_BESTMATCH_CANDIDATES:
        problems.append("BESTMATCH v0c CANDIDATE ANCHOR MISMATCH")
    if int(d.get("field_union_count", 0)) != EXPECTED_SCREENING_UNION:
        problems.append(
            f"BESTMATCH WHOLE-SKÅNE SCREENING UNION {d.get('field_union_count')} != {EXPECTED_SCREENING_UNION}"
        )
    rankings = d.get("rankings") or []
    rank_cols = [str(x.get("column")) for x in rankings if isinstance(x, dict)]
    if rank_cols != ["bestmatch_v0c_rank"]:
        problems.append(f"BESTMATCH SCREENING RANKING IS NOT FROZEN v0c ONLY: {rank_cols}")

    for rel in ("skane_screening.geojson", "skane_estimated_access.geojson"):
        if not (base / rel).is_file():
            problems.append(f"MISSING ACCESS WEB ARTIFACT {rel}")

    geo = load_json(base / "skane_screening.geojson")
    feats = geo.get("features") or []
    if len(feats) != EXPECTED_SCREENING_UNION:
        problems.append(f"BESTMATCH GEOJSON FEATURE COUNT {len(feats)} != {EXPECTED_SCREENING_UNION}")
    by_id = {
        str((f.get("properties") or {}).get("field_id", "")): (f.get("properties") or {})
        for f in feats
    }
    anchors = {
        "61723351559|2A": 1436,
        "61723351559|2B": 273,
    }
    for fid, expected_rank in anchors.items():
        props = by_id.get(fid)
        if not props:
            problems.append(f"BESTMATCH v0c STAFFANSTORP ANCHOR MISSING {fid}")
            continue
        if str(props.get("artkandidat_class")) != "A_STRONG_CANDIDATE":
            problems.append(f"BESTMATCH v0c STAFFANSTORP CLASS WRONG {fid}")
        if str(props.get("rotation_status_v1a")) != "ROTATION_OK_BOUNDARY_SPILL":
            problems.append(f"BESTMATCH v0c STAFFANSTORP ROTATION WRONG {fid}")
        if int(props.get("bestmatch_v0c_rank") or -1) != expected_rank:
            problems.append(
                f"BESTMATCH v0c STAFFANSTORP RANK WRONG {fid}: {props.get('bestmatch_v0c_rank')} != {expected_rank}"
            )

    return {
        "field_union_count": int(d.get("field_union_count", 0)),
        "candidate_fields": int(d.get("candidate_fields", 0)),
        "status": d.get("status"),
    }


def _collect_akerfro_records(dist: Path, wanted: set[str]) -> dict[str, dict]:
    """Read selected field records from the copied municipality ÅkerFrö sidecars."""
    out: dict[str, dict] = {}
    base = dist / "data" / "akerfro"
    for p in sorted(base.rglob("*.json")):
        if p.name == "skane_index.json":
            continue
        try:
            d = load_json(p)
        except Exception:
            continue
        fields = d.get("fields")
        cols = d.get("columns")

        if isinstance(cols, list) and isinstance(fields, dict):
            if "artkandidat_class" not in cols or "rotation_status" not in cols:
                continue
            ci, ri = cols.index("artkandidat_class"), cols.index("rotation_status")
            for fid in wanted.intersection(fields):
                row = fields[fid]
                if isinstance(row, list) and ci < len(row) and ri < len(row):
                    out[fid] = {
                        "artkandidat_class": row[ci],
                        "rotation_status": row[ri],
                    }
        elif isinstance(fields, dict):
            for fid in wanted.intersection(fields):
                row = fields[fid]
                if isinstance(row, dict):
                    out[fid] = {
                        "artkandidat_class": row.get("artkandidat_class"),
                        "rotation_status": row.get("rotation_status"),
                    }
        elif isinstance(fields, list):
            for row in fields:
                if not isinstance(row, dict):
                    continue
                fid = str(row.get("field_id") or row.get("current_field_id") or "")
                if fid in wanted:
                    out[fid] = {
                        "artkandidat_class": row.get("artkandidat_class"),
                        "rotation_status": row.get("rotation_status"),
                    }
    return out


def verify_rotation_v1a(dist: Path, problems: list[str]) -> dict:
    idx = load_json(dist / "data" / "akerfro" / "skane_index.json")
    if idx.get("rotation_policy") != "akerfro-rotation-v1a":
        problems.append("ÅKERFRÖ MUNICIPALITY META MISSING ROTATION v1.1 POLICY")
    if idx.get("rotation_v1a_status") != "FORMALLY_FROZEN":
        problems.append("ÅKERFRÖ ROTATION v1.1 META NOT FROZEN")
    if int(idx.get("rotation_v1a_released_fields", 0)) != EXPECTED_ROTATION_RELEASED:
        problems.append("ÅKERFRÖ ROTATION v1.1 RELEASE META COUNT MISMATCH")

    if not ROTATION.is_file():
        problems.append(f"FROZEN ROTATION v1.1 PRODUCT MISSING: {ROTATION}")
        return {"released_fields": 0}

    rot = pd.read_parquet(
        ROTATION,
        columns=[
            "current_field_id", "artkandidat_class_v1a", "rotation_status_v1a",
            "rotation_v1a_release_candidate",
        ],
    )
    rel = rot[rot["rotation_v1a_release_candidate"].fillna(False).astype(bool)].copy()
    if len(rel) != EXPECTED_ROTATION_RELEASED:
        problems.append(f"FROZEN ROTATION v1.1 RELEASE COUNT {len(rel)} != {EXPECTED_ROTATION_RELEASED}")

    expected = {
        str(r.current_field_id): (str(r.artkandidat_class_v1a), str(r.rotation_status_v1a))
        for r in rel.itertuples(index=False)
    }
    wanted = set(expected) | {"61723353349|94A"}
    got = _collect_akerfro_records(dist, wanted)
    missing = sorted(set(expected) - set(got))
    if missing:
        problems.append(
            f"ROTATION v1.1 RELEASES MISSING FROM MUNICIPALITY SIDECARS: {len(missing)}; "
            + ", ".join(missing[:8])
        )
    for fid, (exp_class, exp_status) in expected.items():
        row = got.get(fid)
        if not row:
            continue
        if str(row.get("artkandidat_class")) != exp_class:
            problems.append(f"ROTATION v1.1 SIDECAR CLASS MISMATCH {fid}")
        if str(row.get("rotation_status")) != exp_status:
            problems.append(f"ROTATION v1.1 SIDECAR STATUS MISMATCH {fid}")

    anchor = got.get("61723353349|94A")
    if not anchor:
        problems.append("ROTATION v1.1 STAFFANSTORP 94A SIDECAR ANCHOR MISSING")
    else:
        if str(anchor.get("artkandidat_class")) != "C_ROTATION_CAUTION":
            problems.append("ROTATION v1.1 STAFFANSTORP 94A CLASS CHANGED")
        if str(anchor.get("rotation_status")) != "CAUTION_RECENT_CONSERVART":
            problems.append("ROTATION v1.1 STAFFANSTORP 94A ROTATION STATUS CHANGED")

    return {"released_fields": len(rel), "sidecar_records_verified": len(set(expected).intersection(got))}

def verify_html(dist: Path, problems: list[str]) -> None:
    p = dist / "index.html"
    if not p.is_file():
        problems.append("MAIN index.html MISSING")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    required = (
        "AKERNORM_WEB_UI_V1", "AKERFRO_ERTOR_WEB_UI_V0A", "AKERFRO_ACCESS_WEB_UI_V0B",
        "AKERVATTEN_WEB_UI_V0A", "AKERVATTEN_VISS_UI_V0A", "AKERPASS_UNIFIED_WEB_V0A",
        'data-layer="fro"', 'data-layer="vatten"', 'data-akv-layer="viss"',
        "window.AKERVATTEN_WEB_CONFIG", "assets/akervatten_v0a.js",
        'href="rapskartan25/"', "$" + "{akervattenSection(p)}",
    )
    for token in required:
        if token not in text:
            problems.append(f"MAIN INDEX MISSING TOKEN {token}")

    ids = re.findall(r'\bid=["\']([^"\']+)["\']', text, flags=re.I)
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        problems.append("DUPLICATE HTML IDS: " + ", ".join(duplicates[:30]))
    verify_local_refs(dist, p, problems)

def verify_raps(dist: Path, problems: list[str]) -> None:
    p = dist / "rapskartan25" / "index.html"
    if not p.is_file():
        problems.append("RAPSKARTAN index.html MISSING")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    if "AKERPASS_RAPSKARTAN_BACKLINK_V0A" not in text or 'href="../"' not in text:
        problems.append("RAPSKARTAN BACKLINK MISSING")
    if "raps" not in text.lower():
        problems.append("RAPSKARTAN INDEX DOES NOT LOOK LIKE RAPSKARTAN")
    verify_local_refs(dist, p, problems)

def dist_manifest(dist: Path) -> list[dict]:
    rows = []
    for p in sorted(x for x in dist.rglob("*") if x.is_file()):
        rows.append({
            "path": p.relative_to(dist).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        })
    return rows

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    args = ap.parse_args()
    dist = args.dist.resolve()
    problems: list[str] = []

    if not dist.is_dir():
        print(f"VERIFY_AKERPASS_UNIFIED_WEB_V0A: FAIL - missing dist {dist}")
        return 2

    build_manifest_path = WORK / "build_manifest.json"
    if not build_manifest_path.is_file():
        problems.append("BUILD MANIFEST MISSING")
        build_manifest = {}
    else:
        build_manifest = load_json(build_manifest_path)
        scope = build_manifest.get("scope") or {}
        if scope.get("models_recalculated") is not False:
            problems.append("BUILD MANIFEST CLAIMS MODEL RECALCULATION")
        if scope.get("new_total_score_created") is not False:
            problems.append("BUILD MANIFEST CLAIMS NEW TOTAL SCORE")
        if scope.get("water_legal_assessment_created") is not False:
            problems.append("BUILD MANIFEST CLAIMS WATER LEGAL ASSESSMENT")
        if scope.get("deployment_performed") is not False:
            problems.append("BUILD MANIFEST CLAIMS DEPLOYMENT")
        frozen = build_manifest.get("frozen_inputs") or {}
        if "bestmatch_v0c" not in frozen:
            problems.append("BUILD MANIFEST MISSING FROZEN BESTMATCH v0c")
        elif int((frozen.get("bestmatch_v0c") or {}).get("candidate_fields", 0)) != EXPECTED_BESTMATCH_CANDIDATES:
            problems.append("BUILD MANIFEST BESTMATCH v0c CANDIDATE ANCHOR MISMATCH")
        if "akerfro_rotation_v1a" not in frozen:
            problems.append("BUILD MANIFEST MISSING FROZEN ROTATION v1.1")
        elif int((frozen.get("akerfro_rotation_v1a") or {}).get("released_fields_patched", 0)) != EXPECTED_ROTATION_RELEASED:
            problems.append("BUILD MANIFEST ROTATION v1.1 RELEASE ANCHOR MISMATCH")

    verify_html(dist, problems)
    rotation = verify_rotation_v1a(dist, problems)
    access = verify_access(dist, problems)
    water = verify_water(dist, problems)
    verify_raps(dist, problems)
    scan_forbidden_text(dist, problems)

    files = dist_manifest(dist)
    total_bytes = sum(x["bytes"] for x in files)
    result = {
        "schema_version": "akerpass-unified-web-verification-v0a",
        "status": "FAIL" if problems else "PASS",
        "repository_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8").strip(),
        "dist": str(dist),
        "files": len(files),
        "bytes": total_bytes,
        "rotation_v1a": rotation,
        "access": access,
        "water_viss": water,
        "rapskartan_present": (dist / "rapskartan25" / "index.html").is_file(),
        "new_total_score_created": False,
        "water_legal_assessment_created": False,
        "problems": problems,
    }
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (WORK / "dist_manifest.json").write_text(json.dumps({
        "schema_version": "akerpass-unified-dist-manifest-v0a",
        "files": files,
        "total_bytes": total_bytes,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 108)
    print("ÅkerPass Unified Preview Web v0a - VERIFY")
    print("=" * 108)
    print(f"Files: {len(files):,} · size: {total_bytes / 1024 / 1024:.1f} MiB")
    print(f"Rotation v1.1 releases verified in municipality sidecars: {rotation.get('sidecar_records_verified', 0):,}/{EXPECTED_ROTATION_RELEASED}")
    print(f"BestMatch v0c candidates: {access.get('candidate_fields', 0):,}")
    print(f"BestMatch v0c screening union: {access.get('field_union_count', 0):,}")
    print(f"ÅkerVatten fields: {water.get('field_count', 0):,}")
    print(f"VISS positive fields: {water.get('viss_positive_fields', 0):,}")
    print(f"Groundwater-level impact fields: {water.get('groundwater_level_impact_fields', 0):,}")
    print("Rapskartan 2025:", "YES" if result["rapskartan_present"] else "NO")
    print("New total score: NO")
    print("Water legal assessment: NO")
    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -", p)
        print("=" * 108)
        print("VERIFY_AKERPASS_UNIFIED_WEB_V0A: FAIL")
        return 2
    print("=" * 108)
    print("VERIFY_AKERPASS_UNIFIED_WEB_V0A: PASS")
    print("=" * 108)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
