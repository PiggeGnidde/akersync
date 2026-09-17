#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only search for original M4 study/source artefacts named by the frozen Technical Note.

Searches historical ÅkerSync/ÅkerMinne work locations for the exact STOPPUNKT artefacts and
likely feature-builder/model-study code. Does not import or execute any discovered code/model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feature/akerpuls-prelim-fields-2026-v0a"
EXPECTED_M0_FREEZE_SHA256 = "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051"
DEFAULT_M0 = Path(r"C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1")
DEFAULT_OUT = Path(r"C:\AkerSyncRepo\work\akerpuls_m4_source_artifact_preflight_v1")
STATUS = "PASS_M4_SOURCE_ARTEFACT_DISCOVERY_STOP"

SEARCH_ROOTS = [
    Path(r"C:\AkerSyncRepo\work"),
    Path(r"C:\AkerSyncRepo\analysis"),
    Path(r"C:\AkerSyncRepo\src"),
    Path(r"C:\AkerSync-Minne"),
    Path(r"C:\AkerSync-Prestation"),
    Path(r"C:\AkerSync-Vaxtfoljd"),
]

EXACT_BASENAMES = {
    "AKERPULS_VAXTFOLJDSMODELL_STUDIE.md",
    "AKERPULS_VAXTFOLJDSMODELL_STUDIE.txt",
    "vaxfoljd_model_report_stoppunkt_c_final.md",
    "vaxfoljd_descriptive_report.md",
    "raps_soft_ablation_final.md",
    "vaxfoljd_manifest.json",
    "vaxfoljd_data_contract.md",
    "vaxfoljd_model_card.md",
}

NAME_TOKENS = (
    "vaxfoljd", "vaxtfoljd", "växtföljd", "raps_soft", "m4_full", "m4-hard", "m4_hard",
)
TEXT_TERMS = (
    "M4_full_pair",
    "M4-hard multiclass",
    "random_state=20260907",
    "random_state":=20260907,
    "n_estimators=35",
    "vaxfoljd_model_report_stoppunkt_c_final",
    "AKERPULS_VAXTFOLJDSMODELL_STUDIE",
    "last 1–3",
    "counts 3/5/7/10",
)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".bat", ".ps1"}
MAX_TEXT_BYTES = 4_000_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_guard() -> str:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Expected branch {EXPECTED_BRANCH}, got {branch}")
    dirty = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Working tree must be clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def find_m0_freeze(root: Path) -> Path:
    hits = []
    for p in root.glob("*.json"):
        try:
            obj = read_json(p)
        except Exception:
            continue
        if obj.get("status") == "FROZEN_AKERPULS_MERGE_M0_SATELLITE_ONLY_V1" and sha256_file(p) == EXPECTED_M0_FREEZE_SHA256:
            hits.append(p)
    if len(hits) != 1:
        raise RuntimeError(f"Could not resolve exact M0 freeze in {root}: {len(hits)} matches")
    return hits[0]


def safe_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def hit_context(text: str, term: str, radius: int = 2) -> list[str]:
    lines = text.splitlines()
    out = []
    t = term.lower()
    for i, line in enumerate(lines):
        if t in line.lower():
            a, b = max(0, i - radius), min(len(lines), i + radius + 1)
            out.append("\n".join(f"{j+1}: {lines[j]}" for j in range(a, b)))
            if len(out) >= 3:
                break
    return out


def should_prune(dirname: str) -> bool:
    low = dirname.lower()
    return low in {".git", "__pycache__", "node_modules", ".venv", "venv"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m0-freeze-dir", default=str(DEFAULT_M0))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    head = git_guard()
    m0 = find_m0_freeze(Path(args.m0_freeze_dir))
    out = Path(args.output_dir)
    if out.exists():
        raise RuntimeError(f"Output directory already exists: {out}")

    records = []
    seen = set()
    roots_state = []
    for root in SEARCH_ROOTS:
        roots_state.append({"root": str(root), "exists": root.is_dir()})
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not should_prune(d)]
            for fn in filenames:
                p = Path(dirpath) / fn
                key = str(p).lower()
                if key in seen:
                    continue
                seen.add(key)
                low = fn.lower()
                exact = fn in EXACT_BASENAMES
                name_signal = any(tok.lower() in low for tok in NAME_TOKENS)
                suffix_ok = p.suffix.lower() in TEXT_SUFFIXES
                text = safe_text(p) if suffix_ok and (exact or name_signal or p.stat().st_size <= MAX_TEXT_BYTES) else ""
                term_hits = [term for term in TEXT_TERMS if term.lower() in text.lower()] if text else []
                if not (exact or name_signal or term_hits):
                    continue
                rec = {
                    "path": str(p),
                    "bytes": int(p.stat().st_size),
                    "sha256": sha256_file(p),
                    "exact_named_artefact": exact,
                    "filename_signal": name_signal,
                    "text_terms": term_hits,
                }
                contexts = {}
                for term in term_hits[:6]:
                    contexts[term] = hit_context(text, term)
                if contexts:
                    rec["contexts"] = contexts
                records.append(rec)

    records.sort(key=lambda r: (not r["exact_named_artefact"], not bool(r["text_terms"]), r["path"].lower()))
    exact = [r for r in records if r["exact_named_artefact"]]
    code = [r for r in records if Path(r["path"]).suffix.lower() == ".py" and r["text_terms"]]

    out.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": "akerpuls-m4-source-artefact-preflight-v1",
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "m0_freeze_sha256": sha256_file(m0),
        "roots": roots_state,
        "exact_basenames": sorted(EXACT_BASENAMES),
        "records": records,
        "exact_named_artefacts_found": len(exact),
        "python_code_with_m4_terms_found": len(code),
        "model_executed": False,
        "m4_prediction_executed": False,
        "fusion_executed": False,
        "thresholds_tuned": False,
        "geometry_mutated": False,
        "next": "REVIEW_ORIGINAL_M4_SOURCE_ARTEFACTS_BEFORE_REPRODUCTION_GATE",
    }
    (out / "M4_SOURCE_ARTEFACT_DISCOVERY_V1.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "AKERPULS M4 SOURCE ARTEFACT PREFLIGHT",
        f"STATUS={STATUS}",
        f"M0_FREEZE_SHA256={sha256_file(m0)}",
        f"ROOTS_CHECKED={len(SEARCH_ROOTS)}",
        f"EXACT_NAMED_ARTEFACTS_FOUND={len(exact)}",
        f"PYTHON_CODE_WITH_M4_TERMS_FOUND={len(code)}",
    ]
    for rs in roots_state:
        lines.append(f"ROOT_EXISTS={str(rs['exists']).upper()} {rs['root']}")
    for r in records:
        flags = []
        if r["exact_named_artefact"]:
            flags.append("EXACT")
        if r["filename_signal"]:
            flags.append("NAME")
        if r["text_terms"]:
            flags.append("TEXT:" + ",".join(r["text_terms"][:5]))
        lines.append(f"FOUND={'|'.join(flags)} {r['path']}")
        for term, ctxs in r.get("contexts", {}).items():
            lines.append(f"  TERM={term}")
            for ctx in ctxs[:2]:
                lines.append("  CONTEXT=" + ctx.replace("\n", " || "))
    lines += [
        "MODEL_EXECUTED=FALSE M4_PREDICTION_EXECUTED=FALSE FUSION_EXECUTED=FALSE",
        "THRESHOLDS_TUNED=FALSE GEOMETRY_MUTATED=FALSE",
        "NEXT=REVIEW_ORIGINAL_M4_SOURCE_ARTEFACTS_BEFORE_REPRODUCTION_GATE",
        f"OUTPUT={out}",
    ]
    txt = "\n".join(lines) + "\n"
    (out / "M4_SOURCE_ARTEFACT_DISCOVERY_V1.txt").write_text(txt, encoding="utf-8")
    print(txt, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
