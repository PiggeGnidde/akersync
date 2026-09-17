#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only ZIP inventory for ÅkerPuls Merge M1 M4 pair prior.

The frozen växtföljdsprior package is stored as one ZIP. This stage inspects the
ZIP in place, hashes every member, classifies likely M4 artefacts, and emits
small text previews. It does not extract files, execute a model, build 2026
features, fuse with satellite evidence, tune thresholds, or mutate geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
DEFAULT_M0_FREEZE_DIR = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
DEFAULT_VAX_ZIP = Path(r"C:\AkerSyncRepo\work\vaxtfoljd_prior_v1_freeze\vaxfoljd_prior_v1_freeze.zip")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_zip_preflight_v1")
STATUS = "PASS_M1_M4_ZIP_DISCOVERY_STOP"
MAX_PREVIEW_BYTES = 16000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def find_exact_m0_freeze(root: Path) -> tuple[Path, dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    hits = []
    for p in root.glob("*.json"):
        try:
            if sha256_file(p) != EXPECTED_M0_FREEZE_SHA256:
                continue
            obj = read_json(p)
        except Exception:
            continue
        if obj.get("status") == "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1":
            hits.append((p, obj))
    if len(hits) != 1:
        raise RuntimeError(f"Could not resolve exact M0 freeze by pinned SHA; matches={len(hits)}")
    return hits[0]


def classify(name: str) -> list[str]:
    low = name.lower().replace("\\", "/")
    base = low.rsplit("/", 1)[-1]
    cats = []
    if any(x in base for x in ("manifest", "freeze", "stoppunkt_e")) and base.endswith((".json", ".md", ".txt")):
        cats.append("manifest_like")
    if any(x in base for x in ("model_card", "modelcard")):
        cats.append("model_card_like")
    if any(x in base for x in ("contract", "data_contract", "feature_contract")):
        cats.append("contract_like")
    if any(x in base for x in ("feature", "build_features", "predict", "prior_export", "export_prior")) and base.endswith((".py", ".json", ".md", ".txt", ".csv")):
        cats.append("feature_or_prediction_code_like")
    if base.endswith((".pkl", ".pickle", ".joblib", ".txt", ".model", ".ubj", ".json")) and any(x in base for x in ("model", "m4", "lightgbm", "booster")):
        cats.append("model_like")
    if any(x in base for x in ("prior_2026", "2026_prior", "prior2026", "prediction_2026", "predictions_2026")):
        cats.append("prior_2026_export_like")
    if any(x in base for x in ("akerminne", "static_context", "akerscore")) and base.endswith((".csv", ".parquet", ".json", ".zip")):
        cats.append("data_input_like")
    return cats


def is_previewable(name: str) -> bool:
    low = name.lower()
    return low.endswith((".json", ".md", ".txt", ".py", ".csv", ".yaml", ".yml"))


def decode_preview(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return "<binary-or-undecodable>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m0-freeze-dir", default=str(DEFAULT_M0_FREEZE_DIR))
    ap.add_argument("--vax-zip", default=str(DEFAULT_VAX_ZIP))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    m0_path, _m0 = find_exact_m0_freeze(Path(args.m0_freeze_dir))
    zpath = Path(args.vax_zip)
    out = Path(args.output_dir)
    if not zpath.is_file():
        raise FileNotFoundError(zpath)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    zip_sha = sha256_file(zpath)
    records = []
    category_map: dict[str, list[str]] = {
        "manifest_like": [], "model_card_like": [], "contract_like": [],
        "feature_or_prediction_code_like": [], "model_like": [],
        "prior_2026_export_like": [], "data_input_like": [],
    }
    previews = []

    with zipfile.ZipFile(zpath, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failed at member {bad}")
        infos = [i for i in zf.infolist() if not i.is_dir()]
        for info in infos:
            data = zf.read(info.filename)
            cats = classify(info.filename)
            rec = {
                "path": info.filename,
                "bytes": int(info.file_size),
                "compressed_bytes": int(info.compress_size),
                "sha256": sha256_bytes(data),
                "categories": cats,
            }
            records.append(rec)
            for c in cats:
                category_map[c].append(info.filename)
            if cats and is_previewable(info.filename) and len(data) <= MAX_PREVIEW_BYTES:
                previews.append({"path": info.filename, "text": decode_preview(data)})

    out.mkdir(parents=True, exist_ok=False)
    result = {
        "schema_version": "akerpuls-merge-m1-m4-zip-discovery-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze_file": str(m0_path),
        "m0_freeze_sha256": EXPECTED_M0_FREEZE_SHA256,
        "vax_zip": str(zpath),
        "vax_zip_sha256": zip_sha,
        "member_count": len(records),
        "categories": category_map,
        "members": records,
        "guards": {
            "zip_extracted": False,
            "model_executed": False,
            "m4_prediction_executed": False,
            "fusion_executed": False,
            "thresholds_tuned": False,
            "geometry_mutated": False,
        },
        "next_stop": "REVIEW_EXACT_ZIP_ARTEFACTS_THEN_IMPLEMENT_M1_ON_FROZEN_27146_PAIR_UNIVERSE",
    }
    (out / "M1_M4_ZIP_DISCOVERY_V1.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# ÅkerPuls M1 M4 ZIP discovery v1", "", f"Status: `{STATUS}`", "",
        f"ZIP: `{zpath}`", f"ZIP SHA-256: `{zip_sha}`", f"Members: {len(records)}", "",
    ]
    for k, vals in category_map.items():
        lines.append(f"## {k} ({len(vals)})")
        lines.extend(f"- `{v}`" for v in vals)
        lines.append("")
    lines += ["## Guards", "No extraction, model execution, M4 prediction, fusion, tuning, or geometry mutation occurred.", ""]
    (out / "M1_M4_ZIP_DISCOVERY_V1.md").write_text("\n".join(lines), encoding="utf-8")

    dump = []
    for p in previews:
        dump += [f"===== BEGIN {p['path']} =====", p["text"], f"===== END {p['path']} =====", ""]
    (out / "M1_M4_RELEVANT_TEXT_PREVIEWS_V1.txt").write_text("\n".join(dump), encoding="utf-8")

    print("AKERPULS MERGE M1 M4 ZIP PREFLIGHT")
    print(f"STATUS={STATUS}")
    print(f"M0_FREEZE_SHA256={EXPECTED_M0_FREEZE_SHA256}")
    print(f"VAX_ZIP_SHA256={zip_sha}")
    print(f"ZIP_MEMBERS={len(records)}")
    for k, vals in category_map.items():
        print(f"{k.upper()}={len(vals)}")
        for v in vals:
            print(f"  {v}")
    print("ZIP_EXTRACTED=FALSE MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE")
    print("THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE")
    print(f"TEXT_PREVIEWS={out / 'M1_M4_RELEVANT_TEXT_PREVIEWS_V1.txt'}")
    print("NEXT=REVIEW_EXACT_ZIP_ARTEFACTS_THEN_IMPLEMENT_M1_ON_FROZEN_27146_PAIR_UNIVERSE")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
