#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerMinne v1a discovery only; produces STOPPUNKT A reports, no history engine."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import load_config
from akerminne_discovery_core import inspect_dataset, inspect_skurup_subset, network_probe, resolve_source

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akerminne_v1a.json"
DEFAULT_LOCAL = ROOT / "config" / "akerminne_local.json"
DEFAULT_PROJECT_LOCAL = ROOT / "config" / "local_paths.json"
OUTPUT_REL = Path("data/derived/akerminne_v1a/discovery")
SCHEMA_VERSION = "akerminne-discovery-v1a"

def repo_contract_summary() -> dict[str, Any]:
    return {
        "baseline_tag": "akerpass-mvp-v1.1",
        "baseline_commit": "be24896c92f55990268a6277383529ff5b406eac",
        "current_2025_input": "config/local_paths.json -> blocks/skiften",
        "current_field_key": "blockid|skiftesbeteckning",
        "current_crop_fields": ["grdkod_mar", "grdkod_und"],
        "municipality_rule_2025": "skifteslagret saknar region_kod; kommun härleds via blockid mot blocklagret",
        "public_data_builder": "src/41_build_akerpass_public_data.py",
        "frontend_builder": "src/42_build_akerpass_frontend.py",
        "frontend_source": "web/akerpass_v1.html",
        "generated_frontend": "dist/index.html",
        "public_municipality_chunks": "dist/data/municipalities/*.json",
        "tests": "python -m unittest discover -s tests",
        "dependency_file": "requirements.txt",
    }


def write_report(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# ÅkerMinne v1a – discovery report", "",
        f"Generated: `{summary['generated_at_utc']}`", "",
        f"Overall status: **{summary['status']}**", "",
        "## Repository contract", "",
    ]
    for k, v in summary["repository"].items():
        lines.append(f"- `{k}`: `{v}`")
    src = summary["official_sources"]
    lines += ["", "## Official source", "", f"- Landing page: {src['landing_page']}", f"- WFS: {src['wfs']}", f"- Verified on: `{src['verified_on']}`", f"- Note: {src['verification_note']}", ""]
    lines += ["## Local annual data", "", "| Year | Skifte | Block | Skurup rows | CRS | Notes |", "|---:|---|---|---:|---|---|"]
    for year in summary["years"]:
        ys = summary["years"][year]
        sm = ys["skiften"]
        bm = ys["blocks"]
        subset = ys["skurup"]
        notes = []
        if sm.get("resolution") in ("not_found", "ambiguous"):
            notes.append("skifte " + sm.get("resolution", ""))
        if bm.get("resolution") in ("not_found", "ambiguous"):
            notes.append("block " + bm.get("resolution", ""))
        if sm.get("inspection", {}).get("error"):
            notes.append("skifte inspect error")
        if bm.get("inspection", {}).get("error"):
            notes.append("block inspect error")
        if not subset.get("available") and subset.get("reason"):
            notes.append(subset["reason"])
        lines.append(
            f"| {year} | {sm.get('resolution')} | {bm.get('resolution')} | "
            f"{subset.get('skifte_rows', '')} | {sm.get('inspection', {}).get('crs', '') or ''} | {'; '.join(notes)} |"
        )
    lines += ["", "## STOPPUNKT A findings", ""]
    for item in summary["findings"]:
        lines.append(f"- {item}")
    lines += ["", "## Network probe", "", f"WFS status: **{summary['network_probe'].get('status')}**"]
    for year, probe in summary["network_probe"].get("years", {}).items():
        lines.append(f"- {year}: {'OK' if probe.get('ok') else 'FAIL'}; fields={', '.join(probe.get('property_names', [])) if probe.get('ok') else probe.get('error','')}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--local-config", default=str(DEFAULT_LOCAL))
    ap.add_argument("--project-local-config", default=str(DEFAULT_PROJECT_LOCAL))
    ap.add_argument("--output", default=str(ROOT / OUTPUT_REL))
    ap.add_argument("--skip-network", action="store_true")
    ap.add_argument("--skip-hash", action="store_true")
    args = ap.parse_args()

    config = load_config(args.config)
    local_cfg = load_config(args.local_config)
    project_cfg = load_config(args.project_local_config)
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("ÅkerMinne v1a · discovery only · STOPPUNKT A")
    print("=" * 78)
    print("Repository baseline:", config.get("field_contract") and "akerpass-mvp-v1.1 / be24896c92f5")
    print("Raw root:", local_cfg.get("raw_root"))
    print("Output:", outdir)

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "repository": repo_contract_summary(),
        "official_sources": config["official_sources"],
        "local_config": {"raw_root": local_cfg.get("raw_root"), "year_override_count": len(local_cfg.get("year_sources") or {})},
        "years": {},
    }

    contract = config["field_contract"]
    local_hist_years = 0
    skurup_years = 0
    for year in config["years"]:
        print(f"\n[{year}] resolving sources ...")
        yr: dict[str, Any] = {}
        for kind in ("skiften", "blocks"):
            resolved = resolve_source(local_cfg, project_cfg, int(year), kind)
            path = Path(resolved["path"]) if resolved.get("path") else None
            inspection = inspect_dataset(path, kind, int(year), do_hash=not args.skip_hash) if path else {"exists": False}
            yr[kind] = {**resolved, "inspection": inspection}
            print(f"  {kind:<7} {resolved['resolution']}: {resolved.get('path') or '-'}")
            if inspection.get("error"):
                print("    ERROR:", inspection["error"])
        yr["skurup"] = inspect_skurup_subset(yr["skiften"]["inspection"], yr["blocks"]["inspection"], contract, str(config["pilot_municipality_code"]))
        if yr["skurup"].get("available"):
            skurup_years += 1
            print(f"  Skurup: {yr['skurup']['skifte_rows']:,} skiften via {yr['skurup']['method']}")
        else:
            print("  Skurup: unavailable -", yr["skurup"].get("reason"))
        hist_inspection = yr["skiften"]["inspection"]
        if int(year) != int(config["reference_year"]) and hist_inspection.get("exists") and not hist_inspection.get("error"):
            local_hist_years += 1
        summary["years"][str(year)] = yr

    if args.skip_network:
        summary["network_probe"] = {"status": "SKIPPED", "years": {}}
    else:
        print("\nLightweight official WFS probe ...")
        summary["network_probe"] = network_probe(
            config["official_sources"], [int(y) for y in config.get("network_probe_years", [])], int(config.get("network_probe_max_features", 5))
        )
        print("  WFS:", summary["network_probe"]["status"])

    findings = []
    if local_hist_years >= 2:
        findings.append(f"Local discovery inspected {local_hist_years} historical skifte year files (requirement >=2 satisfied).")
    else:
        findings.append(f"BLOCKER: only {local_hist_years} historical skifte year files were found locally; at least two are needed before history-engine work starts.")
        summary["status"] = "NEEDS_DATA"
    if skurup_years >= 3:
        findings.append(f"Skurup could be delimited and inspected in {skurup_years} annual datasets.")
    else:
        findings.append(f"BLOCKER: Skurup could be delimited in only {skurup_years} annual datasets; inspect source resolution/block data before continuing.")
        summary["status"] = "NEEDS_DATA"
    ambiguous = []
    for year, yr in summary["years"].items():
        for kind in ("skiften", "blocks"):
            if yr[kind].get("resolution") == "ambiguous":
                ambiguous.append(f"{year} {kind}")
    if ambiguous:
        findings.append("BLOCKER: ambiguous local source candidates: " + ", ".join(ambiguous) + ". Add explicit paths in config/akerminne_local.json.")
        summary["status"] = "NEEDS_DATA"
    network_status = summary["network_probe"].get("status")
    if network_status == "PARTIAL":
        findings.append("Official WFS probe was partial; local discovery results are still valid, but source reachability should be rechecked before downloads.")
    elif network_status == "SKIPPED":
        findings.append("Official WFS probe was explicitly skipped for this discovery run.")
    else:
        findings.append("Official WFS endpoint was probed without a fatal discovery error.")
    findings.append("No ÅkerScore, ÅkerDrift, ÅkerVärde, history engine, batch processing or web UI was modified in this stage.")
    summary["findings"] = findings

    schema_path = outdir / "schema_summary.json"
    report_path = outdir / "discovery_report.md"
    schema_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(summary, report_path)
    print("\n" + "=" * 78)
    print("DISCOVERY EXECUTION: PASS")
    print("Discovery status:", summary["status"])
    print("Report:", report_path)
    print("Schema:", schema_path)
    print("Return both files at STOPPUNKT A; NEEDS_DATA is a discovery finding, not a runner failure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
