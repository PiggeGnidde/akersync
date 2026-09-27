#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT B2 · validate an official NADIA download.

The file itself must be downloaded through SMHI's documented NADIA UI.
This validator does not call or reverse-engineer any undocumented backend.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "akervatten_mvp_v0a" / "b_pilot"
MANIFEST = WORK / "b_pilot_manifest.json"


def norm_id(v: Any) -> str:
    s = str(v).strip()
    return re.sub(r"\.0$", "", s)


def read_excel_any(path: Path) -> dict[str, pd.DataFrame]:
    sig = path.read_bytes()[:8]
    ole = bytes.fromhex("D0CF11E0A1B11AE1")
    if sig == ole:
        return pd.read_excel(path, sheet_name=None, header=None, engine="xlrd", dtype=object)
    if sig[:4] == b"PK\x03\x04":
        try:
            return pd.read_excel(path, sheet_name=None, header=None, engine="openpyxl", dtype=object)
        except ImportError as exc:
            raise RuntimeError(
                "NADIA file is XLSX and openpyxl is not installed. "
                "Install exactly: py -3 -m pip install openpyxl"
            ) from exc
    raise RuntimeError(f"Unknown Excel container: first bytes={sig.hex()}")


def score_sheet(raw: pd.DataFrame, requested: set[str]) -> tuple[int,int,set[str]]:
    best = (-1, -1, set())
    for row_idx in range(min(100, len(raw))):
        vals = [norm_id(v) for v in raw.iloc[row_idx].tolist() if pd.notna(v)]
        hits = set(vals) & requested
        score = len(hits) * 100
        texts = " ".join(vals).lower()
        if any(x in texts for x in ("datum","date","tid","time")):
            score += 10
        if any(x in texts for x in ("vattenför","flow","local","total")):
            score += 5
        if score > best[0]:
            best = (score, row_idx, hits)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("nadia_file", help="Official file downloaded manually from https://vattenwebb.smhi.se/nadia/")
    args = ap.parse_args()

    nadia = Path(args.nadia_file)
    if not nadia.exists():
        raise FileNotFoundError(nadia)
    if not MANIFEST.exists():
        raise FileNotFoundError(f"B pilot manifest missing: {MANIFEST}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = [norm_id(x) for x in manifest["nadia_daily_series"]["sample_ids"]]
    expected_set = set(expected)

    print("="*110)
    print("ÅkerVatten MVP v0a · STOPPUNKT B2 · NADIA DAILY-SERIES VALIDATION")
    print("="*110)
    print("file:", nadia)
    print("expected IDs:", ",".join(expected))

    sheets = read_excel_any(nadia)
    print("sheets:", ", ".join(sheets))

    candidates = []
    all_text_hits = set()
    for name, raw in sheets.items():
        score, header_row, hits = score_sheet(raw, expected_set)
        all_text_hits |= hits
        candidates.append((score, name, header_row, hits))
    candidates.sort(reverse=True, key=lambda x: x[0])

    print("\nTOP SHEETS")
    for score, name, header, hits in candidates[:8]:
        print(f"  {name!r}: score={score}, header_candidate={header}, id_hits={sorted(hits)}")

    # Broad cell-level proof that the requested IDs occur in the official output.
    missing_ids = sorted(expected_set - all_text_hits)

    # Require evidence of a real time axis and numeric series in at least one useful sheet.
    daily_evidence = []
    for _, name, _, _ in candidates:
        raw = sheets[name]
        for row_idx in range(min(100, len(raw))):
            rowtxt = " ".join(
                str(v).strip().lower() for v in raw.iloc[row_idx].tolist()
                if pd.notna(v)
            )
            if not any(token in rowtxt for token in ("datum","date","tid","time")):
                continue
            data = raw.iloc[row_idx+1:].copy()
            if len(data) < 30:
                continue

            # Count rows containing date-like Excel/Python date values or YYYY-MM-DD text.
            date_rows = 0
            numeric_cells = 0
            for _, row in data.head(500).iterrows():
                has_date = False
                for v in row.tolist():
                    if pd.isna(v):
                        continue
                    if hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
                        has_date = True
                    elif re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", str(v).strip()):
                        has_date = True
                    try:
                        fv = float(v)
                        if pd.notna(fv):
                            numeric_cells += 1
                    except Exception:
                        pass
                if has_date:
                    date_rows += 1

            if date_rows >= 30 and numeric_cells >= 30:
                daily_evidence.append({
                    "sheet": name,
                    "header_row_zero_based": row_idx,
                    "date_rows_first_500": date_rows,
                    "numeric_cells_first_500": numeric_cells,
                })
                break

    problems = []
    if missing_ids:
        problems.append(f"requested SUBID absent from NADIA output: {missing_ids}")
    if not daily_evidence:
        problems.append("no sheet with >=30 date rows and >=30 numeric cells was detected")

    result = {
        "schema_version": "akervatten-mvp-v0a-b2-nadia-validation",
        "status": "PASS" if not problems else "FAIL",
        "nadia_file": str(nadia),
        "requested_ids": expected,
        "ids_seen_in_output": sorted(all_text_hits),
        "missing_ids": missing_ids,
        "daily_series_evidence": daily_evidence,
        "problems": problems,
    }
    out = WORK / "b2_nadia_validation.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    print("\nRESULT")
    print("  IDs seen:", ",".join(sorted(all_text_hits)) or "(none)")
    for e in daily_evidence:
        print(
            f"  daily-series evidence: sheet={e['sheet']!r}, "
            f"date_rows={e['date_rows_first_500']}, numeric_cells={e['numeric_cells_first_500']}"
        )

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -", p)

    print("\noutput:", out)
    print("="*110)
    print("AKERVATTEN STOPPUNKT B2 NADIA:", result["status"])
    print("="*110)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
