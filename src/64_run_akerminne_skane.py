#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resumable ÅkerMinne Skåne orchestrator.

Downloads and builds one municipality at a time. Every historical year and
municipality has independent checkpoints, so rerunning after interruption is
safe. By default municipalities are processed from smallest to largest current
2025 field count.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import load_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKANE = ROOT / "data" / "derived" / "akerminne_v1a" / "skane"
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
SCHEMA_VERSION = "akerminne-municipality-v1a-r1"


def _force_utf8_stdio() -> None:
    """Make redirected Windows stdout/stderr deterministic UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _subprocess_env() -> dict[str, str]:
    """Force child Python processes to encode pipes as UTF-8 on Windows."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _atomic_json(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    path.unlink(missing_ok=True)
    tmp.replace(path)


def _slug(text: str) -> str:
    trans = str.maketrans({"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"})
    s = str(text).translate(trans).lower()
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")


def load_plan(root: Path) -> dict[str, Any]:
    path = root / "skane_plan.json"
    if not path.exists():
        raise FileNotFoundError(f"Skåne plan missing: {path}; run 62_prepare_akerminne_skane.py first")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("municipality_count") != 33 or plan.get("current_fields_total") != 128636:
        raise RuntimeError("Skåne plan is not the frozen 33-municipality / 128,636-field plan")
    return plan


def select_municipalities(plan: dict[str, Any], only: str | None, limit: int | None) -> list[dict[str, Any]]:
    by_code = {str(x["code"]): x for x in plan["municipalities"]}
    if only:
        requested = [x.strip() for x in str(only).split(",") if x.strip()]
        unknown = [x for x in requested if x not in by_code]
        if unknown:
            raise ValueError(f"Unknown municipality codes in --only: {unknown}")
        selected = [by_code[x] for x in requested]
    else:
        order = [str(x) for x in plan.get("order_small_first") or sorted(by_code)]
        selected = [by_code[x] for x in order]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be >=1")
        selected = selected[:limit]
    return selected


def municipality_dir(skane_root: Path, item: dict[str, Any]) -> Path:
    return skane_root / "municipalities" / f"{item['code']}_{_slug(item['name'])}"


def is_complete(skane_root: Path, item: dict[str, Any]) -> bool:
    path = municipality_dir(skane_root, item) / "build_manifest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return (
            doc.get("schema_version") == SCHEMA_VERSION
            and str(doc.get("municipality_code")) == str(item["code"])
            and int(doc.get("current_fields", -1)) == int(item["current_fields"])
            and int(doc.get("field_years", -1)) == int(item["current_fields"]) * 11
        )
    except Exception:
        return False


def run_checked(cmd: list[str], label: str, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n--- {label} ---")
    print(" ".join(cmd))
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n\n=== {datetime.now(timezone.utc).isoformat()} · {label} ===\n")
        log.flush()
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_subprocess_env(),
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        rc = process.wait()
    if rc != 0:
        raise RuntimeError(f"{label} failed with exit code {rc}; see {log_path}")


def main() -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--skane-root", default=str(DEFAULT_SKANE))
    ap.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    ap.add_argument("--only", help="Comma-separated municipality codes")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--rebuild-complete", action="store_true")
    args = ap.parse_args()

    skane_root = Path(args.skane_root)
    plan = load_plan(skane_root)
    local_cfg = load_config(args.local_config)
    raw_root = Path(local_cfg["raw_root"])
    selected = select_municipalities(plan, args.only, args.limit)
    progress_path = skane_root / "progress.json"
    log_root = skane_root / "logs"

    progress: dict[str, Any] = {
        "schema_version": "akerminne-skane-progress-v1",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_codes": [str(x["code"]) for x in selected],
        "municipalities": {},
    }
    if progress_path.exists():
        try:
            old = json.loads(progress_path.read_text(encoding="utf-8"))
            if isinstance(old.get("municipalities"), dict):
                progress["municipalities"].update(old["municipalities"])
        except Exception:
            pass

    print("=" * 78)
    print("ÅkerMinne v1a · SKÅNE RESUMABLE BATCH")
    print("=" * 78)
    print(f"Selected municipalities: {len(selected)}")
    print("Order:", ", ".join(f"{x['code']} {x['name']}" for x in selected))
    print(f"Raw root: {raw_root}")
    print(f"Derived root: {skane_root}")

    batch_start = time.perf_counter()
    for idx, item in enumerate(selected, 1):
        code, name = str(item["code"]), str(item["name"])
        rec = progress["municipalities"].setdefault(code, {})
        rec.update({"name": name, "current_fields": int(item["current_fields"]), "started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "RUNNING"})
        _atomic_json(progress, progress_path)
        print("\n" + "#" * 78)
        print(f"[{idx}/{len(selected)}] {name} ({code}) · current fields {int(item['current_fields']):,}")
        print("#" * 78)

        if not args.rebuild_complete and is_complete(skane_root, item):
            print("Municipality already complete for pipeline r1 · SKIP")
            rec["status"] = "PASS"
            rec["skipped_complete"] = True
            rec["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(progress, progress_path)
            continue

        t0 = time.perf_counter()
        try:
            if not args.skip_download:
                download_cmd = [
                    sys.executable,
                    str(ROOT / "src" / "51_download_akerminne_pilot.py"),
                    "--out-root", str(raw_root / "akerminne_v1a"),
                    "--years", *[str(y) for y in range(2015, 2025)],
                    "--municipality", name,
                    "--municipality-code", code,
                ]
                run_checked(download_cmd, f"{name} historical download 2015-2024", log_root / f"{code}_download.log")

            build_cmd = [
                sys.executable,
                str(ROOT / "src" / "63_build_akerminne_municipality.py"),
                "--municipality", name,
                "--municipality-code", code,
                "--skane-root", str(skane_root),
                "--resume",
            ]
            run_checked(build_cmd, f"{name} ÅkerMinne build 2015-2025", log_root / f"{code}_build.log")
            if not is_complete(skane_root, item):
                raise RuntimeError("Build returned success but final municipality manifest is incomplete")
            rec.update({"status": "PASS", "skipped_complete": False, "elapsed_seconds": round(time.perf_counter() - t0, 3), "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            _atomic_json(progress, progress_path)
        except Exception as exc:
            rec.update({"status": "FAIL", "error": str(exc), "elapsed_seconds": round(time.perf_counter() - t0, 3), "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            progress["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(progress, progress_path)
            print("\n" + "=" * 78)
            print(f"AKERMINNE SKÅNE BATCH: FAIL at {name} ({code})")
            print("=" * 78)
            print(exc)
            print(f"Progress preserved: {progress_path}")
            print("Rerun the same command after inspection; completed years/municipalities are reused.")
            return 1

        progress["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(progress, progress_path)

    elapsed = time.perf_counter() - batch_start
    completed = sum(1 for item in selected if is_complete(skane_root, item))
    print("\n" + "=" * 78)
    print("AKERMINNE SKÅNE BATCH: PASS")
    print("=" * 78)
    print(f"Selected completed: {completed}/{len(selected)}")
    print(f"Elapsed: {elapsed/60:.1f} min")
    print(f"Progress: {progress_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
