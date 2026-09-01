#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import itertools
import json
import math
import re
import subprocess
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCHEMA_VERSION = "akernorm-v1-discovery-v1"
CONTEXT_TAG = "akerpass-akerminne-context-v1.0"
CONTEXT_COMMIT = "1ad5c77656bb93664d94254af298009a6620da4f"
VALIDATION_TAG = "akerscore-akerminne-validation-v1.0"
VALIDATION_COMMIT = "9ca92418d6c100793dcaf3ae70705c97e556a9d5"
ANALYSIS_BRANCH = "feature/akerscore-normskord-validation-v0a"
ANALYSIS_COMMIT = "0d889b5acd2aa99a3bf70c66b67b63dd79b2b846"
FEATURE_BRANCH = "feature/akernorm-product-v1a"
ANALYSIS_DIR = Path("analysis/akerscore_normskord_validation_v0a")
API_URL = (
    "https://statistik.sjv.se/PXWeb/api/v1/sv/"
    "Jordbruksverkets%20statistikdatabas/Skordar/Normskord/JO0602A03.px"
)
SKO_DOMAIN = [
    "0731", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
]
GEOGRAPHIC_CORE_EXCLUSIONS = {"0731", "1124", "1131", "1321"}

EXPECTED_INPUTS = {
    "field_static_context_selected.csv.gz": {
        "rows": 128_636,
        "sha256": "31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea",
    },
    "akerminne_2015_2025_selected.csv.gz": {
        "rows": 1_414_996,
        "sha256": "05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf",
    },
    "akerscore_soil_skiften_selected.csv.gz": {
        "rows": 128_636,
        "sha256": "71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da",
    },
}

CROPS = [
    {"key": "hostvete", "canonical_code": 4, "annual_name": "Vete (höst)", "pxweb_labels": ["Höstvete"]},
    {"key": "varkorn", "canonical_code": 2, "annual_name": "Korn (vår)", "pxweb_labels": ["Vårkorn"]},
    {"key": "havre", "canonical_code": 3, "annual_name": "Havre", "pxweb_labels": ["Havre"]},
    {"key": "hostraps", "canonical_code": 20, "annual_name": "Raps (höst)", "pxweb_labels": ["Höstraps"]},
    {"key": "matpotatis", "canonical_code": 45, "annual_name": "Matpotatis", "pxweb_labels": ["Matpotatis"]},
    {"key": "starkelsepotatis", "canonical_code": 46, "annual_name": "Stärkelsepotatis", "pxweb_labels": ["Potatis för stärkelse"]},
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def repository_snapshot(root: Path) -> dict[str, Any]:
    context = git(root, "rev-list", "-n", "1", CONTEXT_TAG)
    validation = git(root, "rev-list", "-n", "1", VALIDATION_TAG)
    analysis_remote = git(root, "rev-parse", f"origin/{ANALYSIS_BRANCH}")
    branch = git(root, "branch", "--show-current")
    status = git(root, "status", "--short")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", CONTEXT_COMMIT, "HEAD"], cwd=root
    ).returncode == 0
    imported_diff = git(root, "diff", "--name-only", ANALYSIS_COMMIT, "HEAD", "--", str(ANALYSIS_DIR))
    return {
        "schema_version": SCHEMA_VERSION,
        "repository_root": str(root),
        "branch": branch,
        "head": git(root, "rev-parse", "HEAD"),
        "working_tree_clean": not bool(status),
        "git_status_short": status.splitlines(),
        "context_tag": CONTEXT_TAG,
        "context_commit_actual": context,
        "context_commit_expected": CONTEXT_COMMIT,
        "validation_tag": VALIDATION_TAG,
        "validation_commit_actual": validation,
        "validation_commit_expected": VALIDATION_COMMIT,
        "analysis_branch": ANALYSIS_BRANCH,
        "analysis_commit_actual": analysis_remote,
        "analysis_commit_expected": ANALYSIS_COMMIT,
        "context_is_ancestor_of_head": ancestor,
        "imported_analysis_diff_paths": imported_diff.splitlines() if imported_diff else [],
    }


def verify_repository_snapshot(snapshot: dict[str, Any]) -> list[str]:
    failures = []
    checks = [
        (snapshot["branch"] == FEATURE_BRANCH, f"branch is {snapshot['branch']}, expected {FEATURE_BRANCH}"),
        (snapshot["working_tree_clean"], "working tree is not clean"),
        (snapshot["context_commit_actual"] == CONTEXT_COMMIT, "context tag commit mismatch"),
        (snapshot["validation_commit_actual"] == VALIDATION_COMMIT, "validation tag commit mismatch"),
        (snapshot["analysis_commit_actual"] == ANALYSIS_COMMIT, "analysis branch commit mismatch"),
        (snapshot["context_is_ancestor_of_head"], "context commit is not an ancestor of HEAD"),
        (not snapshot["imported_analysis_diff_paths"], "imported analysis differs from identified analysis commit"),
    ]
    for passed, message in checks:
        if not passed:
            failures.append(message)
    return failures


def analysis_inventory(root: Path) -> dict[str, Any]:
    directory = root / ANALYSIS_DIR
    paths = sorted(p for p in directory.rglob("*") if p.is_file())
    suffix_counts: dict[str, int] = {}
    files = []
    for path in paths:
        suffix = path.suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        files.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    commits = git(root, "log", "--reverse", "--format=%H%x09%s", f"{VALIDATION_COMMIT}..{ANALYSIS_COMMIT}")
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_branch": ANALYSIS_BRANCH,
        "analysis_commit": ANALYSIS_COMMIT,
        "merge_base_with_context": git(root, "merge-base", CONTEXT_COMMIT, ANALYSIS_COMMIT),
        "commit_count_after_validation": len(commits.splitlines()),
        "commits_after_validation": commits.splitlines(),
        "file_count": len(files),
        "suffix_counts": suffix_counts,
        "files": files,
        "filters": {
            "history_years": "2015-2025",
            "history_status": "SINGLE_CROP",
            "minimum_dominant_sko_share": 0.95,
            "weight": "current_area_m2 per qualifying field-year",
            "score": "akerscore_soil_p50",
        },
        "tests": "No dedicated unit-test file in the identified analysis directory.",
        "manifests": "Input hashes are embedded in run_validation.py; the same hashes are frozen in the validation-tag input manifest.",
    }


def verify_frozen_inputs(input_dir: Path) -> dict[str, Any]:
    files = {}
    failures = []
    for name, expected in EXPECTED_INPUTS.items():
        path = input_dir / name
        rec = {"path": str(path), "exists": path.exists(), **expected}
        if path.exists():
            rec["actual_sha256"] = sha256_file(path)
            rec["sha256_match"] = rec["actual_sha256"] == expected["sha256"]
            if not rec["sha256_match"]:
                failures.append(f"{name}: SHA256 mismatch")
            rec["actual_rows"] = int(sum(len(chunk) for chunk in pd.read_csv(path, usecols=[0], chunksize=200_000)))
            rec["row_count_match"] = rec["actual_rows"] == expected["rows"]
            if not rec["row_count_match"]:
                failures.append(
                    f"{name}: row count {rec['actual_rows']:,} != expected {expected['rows']:,}"
                )
        else:
            rec["sha256_match"] = False
            rec["row_count_match"] = False
            failures.append(f"{name}: missing")
        files[name] = rec
    return {"status": "PASS" if not failures else "BLOCKED", "files": files, "failures": failures}


def _normalized(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.casefold().split())


def _decode_annual_table(path: Path, expected_hash: str) -> list[dict[str, str]]:
    raw = gzip.decompress(base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True))
    actual = sha256_bytes(raw)
    if actual != expected_hash:
        raise RuntimeError(f"{path.name}: normalized annual crop dictionary SHA256 mismatch")
    return list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))


def build_crop_code_contract(root: Path) -> dict[str, Any]:
    dictionary_dir = root / "data/reference/akerminne_crop_codes_official"
    manifest = json.loads((dictionary_dir / "manifest.json").read_text(encoding="utf-8"))
    reference_2026 = pd.read_csv(root / "data/reference/grodkoder_2026_reference.csv", dtype=str)
    ref_names = dict(zip(reference_2026["crop_code"], reference_2026["crop_name_reference_2026"]))
    crop_rows = []
    errors = []
    for crop in CROPS:
        annual = []
        code = str(crop["canonical_code"])
        for year in range(2015, 2026):
            meta = manifest["years"][str(year)]
            rows = _decode_annual_table(dictionary_dir / meta["payload_file"], meta["normalized_sha256"])
            matches = [r for r in rows if str(r.get("crop_code_raw", "")).strip() == code and not str(r.get("crop_subcategory_raw", "")).strip()]
            status = "PASS" if len(matches) == 1 and matches[0]["crop_name"] == crop["annual_name"] else "MISMATCH"
            if status != "PASS":
                errors.append(f"{year}/{code}: expected {crop['annual_name']!r}, found {[r.get('crop_name') for r in matches]}")
            annual.append({
                "year": year,
                "raw_crop_code": code,
                "raw_crop_name": matches[0]["crop_name"] if len(matches) == 1 else None,
                "dictionary_payload": meta["payload_file"],
                "dictionary_normalized_sha256": meta["normalized_sha256"],
                "status": status,
            })
        ref_name = ref_names.get(code)
        if ref_name != crop["annual_name"]:
            errors.append(f"2026 reference/{code}: expected {crop['annual_name']!r}, found {ref_name!r}")
        crop_rows.append({
            "crop_key": crop["key"],
            "canonical_crop_code": crop["canonical_code"],
            "canonical_name": crop["annual_name"],
            "annual_mappings": annual,
            "reference_2026_name": ref_name,
            "pxweb_label_candidates": crop["pxweb_labels"],
        })
    return {
        "schema_version": "akernorm-v1-crop-code-contract-discovery-v1",
        "status": "PASS" if not errors else "MISMATCH",
        "source_manifest": "data/reference/akerminne_crop_codes_official/manifest.json",
        "source_manifest_sha256": sha256_file(dictionary_dir / "manifest.json"),
        "mapping_rule": "Exact annual main code; no cross-year fallback.",
        "analysis_population": "SINGLE_CROP only; repeated field-years remain repeated and are area-year weighted.",
        "future_product_presence_rule_discovered": {
            "dominant_presence": "qualified historical year",
            "mixed_component_materiality": 0.05,
            "config_path": "config/akerminne_v1a.json/history_status/mixed_secondary_crop_min_share",
            "note": "Product presence is recorded for later model-freeze work; it is not implemented in discovery.",
        },
        "crops": crop_rows,
        "errors": errors,
    }


def _http_bytes(url: str, payload: dict[str, Any] | None = None) -> bytes:
    headers = {"User-Agent": "AkerSync AkerNorm discovery/1.0"}
    if payload is None:
        request = urllib.request.Request(url, headers=headers)
    else:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _find_var(meta: dict[str, Any], wanted: str) -> dict[str, Any]:
    needle = _normalized(wanted)
    matches = [
        var
        for var in meta["variables"]
        if needle in {
            _normalized(var.get("code", "")),
            _normalized(var.get("text", "")),
        }
    ]
    if len(matches) != 1:
        available = [
            {"code": str(var.get("code", "")), "text": str(var.get("text", ""))}
            for var in meta.get("variables", [])
        ]
        raise RuntimeError(
            f"PXWeb dimension {wanted!r}: expected one exact code/text match, "
            f"found {len(matches)}; available dimensions: {available}"
        )
    return matches[0]


def _resolve_value(var: dict[str, Any], candidates: list[str]) -> tuple[str, str]:
    values = [(str(c), str(t)) for c, t in zip(var.get("values", []), var.get("valueTexts", []))]
    for candidate in candidates:
        exact = [(c, t) for c, t in values if _normalized(t) == _normalized(candidate)]
        if len(exact) == 1:
            return exact[0]
    raise RuntimeError(
        f"PXWeb value not found for {candidates}; available labels: {[t for _, t in values]}"
    )


def _jsonstat_categories(document: dict[str, Any], dim_id: str) -> tuple[list[str], dict[str, str]]:
    category = document["dimension"][dim_id]["category"]
    index = category["index"]
    if isinstance(index, dict):
        ordered: list[str | None] = [None] * len(index)
        for code, position in index.items():
            ordered[int(position)] = str(code)
        codes = [str(value) for value in ordered]
    else:
        codes = [str(value) for value in index]
    return codes, {str(k): str(v) for k, v in category.get("label", {}).items()}


def _flatten_jsonstat(document: dict[str, Any]) -> list[dict[str, Any]]:
    ids = list(document["id"])
    sizes = list(document["size"])
    values = document["value"]
    if isinstance(values, dict):
        dense = [None] * int(math.prod(sizes))
        for index, value in values.items():
            dense[int(index)] = value
        values = dense
    array = np.asarray(values, dtype=object).reshape(sizes)
    categories = {dim: _jsonstat_categories(document, dim) for dim in ids}
    rows = []
    for coordinate in itertools.product(*[range(size) for size in sizes]):
        row: dict[str, Any] = {}
        for dim, position in zip(ids, coordinate):
            codes, labels = categories[dim]
            code = codes[position]
            row[dim] = labels.get(code, code)
            row[f"{dim}__code"] = code
        row["value"] = array[coordinate]
        rows.append(row)
    return rows


def _sko_id(text: str) -> str | None:
    match = re.search(r"\b(\d{4})\*?\b", str(text))
    return match.group(1) if match else None


def fetch_official_norms(source_dir: Path, api_url: str = API_URL) -> dict[str, Any]:
    raw_dir = source_dir / "raw"
    query_dir = source_dir / "queries"
    normalized_dir = source_dir / "normalized"
    for directory in (raw_dir, query_dir, normalized_dir):
        directory.mkdir(parents=True, exist_ok=True)

    metadata_raw = _http_bytes(api_url)
    metadata_path = raw_dir / "JO0602A03_metadata_raw.json"
    metadata_path.write_bytes(metadata_raw)
    metadata = json.loads(metadata_raw.decode("utf-8-sig"))
    v_sko = _find_var(metadata, "Skördeområde")
    v_year = _find_var(metadata, "År")
    v_crop = _find_var(metadata, "Gröda")
    v_measure = _find_var(metadata, "Variabel")
    year_code, year_text = _resolve_value(v_year, ["2026"])

    all_rows = []
    crop_sources = []
    legacy_paths: dict[str, str] = {}
    for crop in CROPS:
        crop_code, crop_text = _resolve_value(v_crop, crop["pxweb_labels"])
        query = {
            "query": [
                {"code": v_sko["code"], "selection": {"filter": "all", "values": ["*"]}},
                {"code": v_year["code"], "selection": {"filter": "item", "values": [year_code]}},
                {"code": v_crop["code"], "selection": {"filter": "item", "values": [crop_code]}},
                {"code": v_measure["code"], "selection": {"filter": "all", "values": ["*"]}},
            ],
            "response": {"format": "json-stat2"},
        }
        query_path = query_dir / f"JO0602A03_{crop['key']}_2026_query.json"
        stable_json(query_path, query)
        response_raw = _http_bytes(api_url, query)
        raw_path = raw_dir / f"JO0602A03_{crop['key']}_2026_raw.json"
        raw_path.write_bytes(response_raw)
        response = json.loads(response_raw.decode("utf-8-sig"))
        by_sko = {sko: {"norm": None, "companies": None, "norm_measure": None, "companies_measure": None} for sko in SKO_DOMAIN}
        for row in _flatten_jsonstat(response):
            sko = _sko_id(row.get(v_sko["code"], ""))
            if sko not in by_sko or row.get("value") is None:
                continue
            measure = str(row.get(v_measure["code"], ""))
            normalized_measure = _normalized(measure)
            if "normskord" in normalized_measure and ("kg" in normalized_measure or "hektar" in normalized_measure):
                by_sko[sko]["norm"] = float(row["value"])
                by_sko[sko]["norm_measure"] = measure
            elif "antal foretag" in normalized_measure:
                by_sko[sko]["companies"] = float(row["value"])
                by_sko[sko]["companies_measure"] = measure

        legacy_path = normalized_dir / f"normskord_{crop['key']}_2026.csv"
        with legacy_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sko_id", "norm_kg_ha", "n_companies", "source_note"], lineterminator="\n")
            writer.writeheader()
            for sko in SKO_DOMAIN:
                item = by_sko[sko]
                norm = "" if item["norm"] is None else int(round(item["norm"]))
                companies = "" if item["companies"] is None else int(round(item["companies"]))
                writer.writerow({
                    "sko_id": sko, "norm_kg_ha": norm, "n_companies": companies,
                    "source_note": f"Jordbruksverket PXWeb JO0602A03, {crop_text}, 2026",
                })
                all_rows.append({
                    "crop_key": crop["key"],
                    "crop_code_canonical": crop["canonical_code"],
                    "pxweb_crop_code": crop_code,
                    "pxweb_crop_text": crop_text,
                    "sko_id": sko,
                    "official_norm_year": 2026,
                    "norm_raw_value": item["norm"],
                    "norm_raw_unit": "kg/ha" if item["norm"] is not None else None,
                    "official_norm_t_ha": None if item["norm"] is None else item["norm"] / 1000.0,
                    "n_companies": item["companies"],
                    "status": "PUBLISHED" if item["norm"] is not None else "MISSING_OR_SUPPRESSED",
                })
        legacy_paths[crop["key"]] = str(legacy_path)
        crop_sources.append({
            "crop_key": crop["key"], "resolved_crop_code": crop_code, "resolved_crop_text": crop_text,
            "year_code": year_code, "year_text": year_text,
            "query_path": str(query_path), "query_sha256": sha256_file(query_path),
            "raw_response_path": str(raw_path), "raw_response_sha256": sha256_file(raw_path),
            "normalized_legacy_path": str(legacy_path), "normalized_legacy_sha256": sha256_file(legacy_path),
            "published_sko": sum(1 for value in by_sko.values() if value["norm"] is not None),
        })

    normalized_path = normalized_dir / "official_norm_yield_2026_normalized.csv"
    pd.DataFrame(all_rows).to_csv(normalized_path, index=False, encoding="utf-8", lineterminator="\n")
    return {
        "table": "JO0602A03",
        "title": "Normskörd efter skördeområde och gröda. År 2003-2026",
        "api_url": api_url,
        "retrieved_at_utc": utc_now(),
        "metadata_raw_path": str(metadata_path),
        "metadata_raw_sha256": sha256_file(metadata_path),
        "raw_unit": "kg/ha",
        "normalized_unit": "t/ha",
        "conversion": "t/ha = kg/ha / 1000",
        "normalized_path": str(normalized_path),
        "normalized_sha256": sha256_file(normalized_path),
        "crop_sources": crop_sources,
        "legacy_paths": legacy_paths,
    }


def run_logged(command: list[str], cwd: Path, log_path: Path) -> None:
    print("COMMAND:", subprocess.list2cmdline(command), flush=True)
    proc = subprocess.run(
        command, cwd=cwd, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout, encoding="utf-8")
    print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    if proc.returncode:
        raise RuntimeError(f"Command failed with exit code {proc.returncode}: {subprocess.list2cmdline(command)}")


def _fit_positive_linear(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    x_mean, y_mean = x.mean(), y.mean()
    denominator = float(np.sum((x - x_mean) ** 2))
    slope = 0.0 if denominator <= 0 else float(np.sum((x - x_mean) * (y - y_mean)) / denominator)
    slope = max(0.0, slope)
    intercept = float(np.mean(y - slope * x))
    prediction = intercept + slope * x
    error = y - prediction
    sst = float(np.sum((y - y_mean) ** 2))
    return {
        "intercept_t_ha": intercept,
        "slope_t_ha_per_score": slope,
        "effect_t_ha_per_10_score": slope * 10.0,
        "r2": float(1.0 - np.sum(error ** 2) / sst) if sst > 0 else float("nan"),
    }


def _linear_loocv(x: np.ndarray, y: np.ndarray) -> float:
    prediction = np.empty(len(y), dtype=float)
    for index in range(len(y)):
        keep = np.arange(len(y)) != index
        fit = _fit_positive_linear(x[keep], y[keep])
        prediction[index] = fit["intercept_t_ha"] + fit["slope_t_ha_per_score"] * x[index]
    return float(np.sqrt(np.mean((y - prediction) ** 2)))


def score_only_core_metrics(path: Path, exclusions: set[str] = GEOGRAPHIC_CORE_EXCLUSIONS) -> dict[str, Any]:
    frame = pd.read_csv(path, dtype={"sko_id": str})
    frame["sko_id"] = frame["sko_id"].astype(str).str.zfill(4)
    frame = frame[~frame["sko_id"].isin(exclusions)].copy()
    frame = frame.dropna(subset=["mean_akerscore_areaweighted", "norm_t_ha"]).sort_values("sko_id")
    x = frame["mean_akerscore_areaweighted"].to_numpy(float)
    y = frame["norm_t_ha"].to_numpy(float)
    fit = _fit_positive_linear(x, y)
    return {
        "n_sko": int(len(frame)),
        "sko_ids": frame["sko_id"].tolist(),
        **fit,
        "loocv_rmse_t_ha": _linear_loocv(x, y),
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def actual_reproduction_metrics(reproduction_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    actual: dict[tuple[str, str], dict[str, Any]] = {}

    wheat = load_json(reproduction_dir / "hostvete/base/results.json")
    actual[("hostvete_score_only", "all_published")] = {
        "n_sko": wheat["published_sko_used"], **wheat["linear_primary"]
    }
    wheat_climate = load_json(reproduction_dir / "hostvete/climate_excl_sparse/climate_results.json")
    wc = wheat_climate["models"]["score_plus_climate"]
    actual[("hostvete_score_plus_climate", "exclude_1321_1124_1221")] = {
        "n_sko": wheat_climate["n_sko"],
        "effect_t_ha_per_10_score": wc["coefficients"]["akerscore_per_10"],
        "r2": wc["r2"],
        "loocv_rmse_t_ha": wc["loocv_rmse_t_ha"],
    }

    for key, analysis in [("varkorn", "varkorn_score_only"), ("havre", "havre_score_only"), ("hostraps", "hostraps_score_only")]:
        result = load_json(reproduction_dir / f"{key}/base/results.json")
        actual[(analysis, "all_published")] = {"n_sko": result["n_sko"], **result["linear"]}
        actual[(analysis, "geographic_core")] = score_only_core_metrics(reproduction_dir / f"{key}/base/sko_fit_table.csv")

    for key, analysis in [("matpotatis", "matpotatis_score_only"), ("starkelsepotatis", "starkelsepotatis_score_only")]:
        result = load_json(reproduction_dir / f"{key}/base/results.json")
        actual[(analysis, "all_published")] = {"n_sko": result["n_sko"], **result["linear"]}
        if key == "matpotatis":
            actual[(analysis, "geographic_core")] = score_only_core_metrics(reproduction_dir / f"{key}/base/sko_fit_table.csv")
    return actual


def compare_reproduction(expected_path: Path, reproduction_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected_doc = load_json(expected_path)
    default_tolerance = float(expected_doc["absolute_tolerance_for_reported_3_decimal_metrics"])
    actual = actual_reproduction_metrics(reproduction_dir)
    rows = []
    for expected in expected_doc["comparisons"]:
        key = (expected["analysis"], expected["population"])
        observed = actual.get(key)
        for metric in ("n_sko", "effect_t_ha_per_10_score", "r2", "loocv_rmse_t_ha"):
            target = expected[metric]
            value = None if observed is None else observed.get(metric)
            tolerance = 0.0 if metric == "n_sko" else float(expected.get(f"{metric}_tolerance", default_tolerance))
            passed = value is not None and abs(float(value) - float(target)) <= tolerance
            rows.append({
                "analysis": key[0], "population": key[1], "metric": metric,
                "reported": target, "reproduced": value, "absolute_tolerance": tolerance,
                "difference": None if value is None else float(value) - float(target),
                "status": "PASS" if passed else "MISMATCH",
            })
    comparison = pd.DataFrame(rows)

    decisions: dict[str, Any] = {
        "status": "PASS" if (comparison["status"] == "PASS").all() else "MISMATCH",
        "climate_selected_for_v1": False,
        "potato_score_adjusted_in_v1": False,
        "guard_checks": [],
        "reasoning": [],
    }
    winter_all = load_json(reproduction_dir / "hostvete/climate_all/climate_results.json")
    winter_core = load_json(reproduction_dir / "hostvete/climate_excl_sparse/climate_results.json")
    decisions["reasoning"].append({
        "crop": "hostvete",
        "all_sko_delta_loocv_rmse": winter_all["diagnostics"]["delta_loocv_rmse_score_plus_climate_vs_score_only"],
        "sensitivity_delta_loocv_rmse": winter_core["diagnostics"]["delta_loocv_rmse_score_plus_climate_vs_score_only"],
        "decision": "Sensitivity is recorded but does not replace the full-population score-only V1 contract.",
    })
    decisions["guard_checks"].append({
        "name": "winter_wheat_climate_result_is_sensitivity_not_full_population",
        "passed": winter_all["n_sko"] == 15 and winter_core["n_sko"] == 12,
        "observed": {"full_n_sko": winter_all["n_sko"], "sensitivity_n_sko": winter_core["n_sko"]},
    })
    for crop in ("havre", "hostraps"):
        climate = load_json(reproduction_dir / f"{crop}/climate_all/climate_results.json")
        decisions["reasoning"].append({
            "crop": crop,
            "n_sko": climate["n_sko"],
            "delta_loocv_rmse": climate["diagnostics"]["delta_loocv_rmse_score_plus_climate_vs_score_only"],
            "decision": "Climate is not selected for V1.",
        })
        if crop == "hostraps":
            decisions["guard_checks"].append({
                "name": "winter_rapeseed_climate_does_not_improve_loocv",
                "passed": climate["diagnostics"]["delta_loocv_rmse_score_plus_climate_vs_score_only"] >= -1e-12,
                "observed_delta_loocv_rmse": climate["diagnostics"]["delta_loocv_rmse_score_plus_climate_vs_score_only"],
            })
    oat_core = actual[("havre_score_only", "geographic_core")]
    decisions["guard_checks"].append({
        "name": "oat_geographic_core_too_small_for_four_parameter_climate_model",
        "passed": oat_core["n_sko"] == 7 and oat_core["n_sko"] < 8,
        "observed_n_sko": oat_core["n_sko"],
    })
    table_potato = actual[("matpotatis_score_only", "all_published")]
    starch_potato = actual[("starkelsepotatis_score_only", "all_published")]
    decisions["guard_checks"].append({
        "name": "potato_score_only_evidence_is_weak_or_small_n",
        "passed": table_potato["r2"] < 0.15 and starch_potato["r2"] < 0.15 and starch_potato["n_sko"] < 8,
        "observed": {
            "matpotatis_r2": table_potato["r2"],
            "starkelsepotatis_r2": starch_potato["r2"],
            "starkelsepotatis_n_sko": starch_potato["n_sko"],
        },
    })
    decisions["reasoning"].append({
        "crop": "potato",
        "decision": "Official-SKO-only guardrail retained because score-only fits are weak/small-n and climate is not a pre-registered V1 input.",
    })
    if not all(item["passed"] for item in decisions["guard_checks"]):
        decisions["status"] = "MISMATCH"
    return comparison, decisions


def artifact_hashes(root: Path) -> dict[str, dict[str, Any]]:
    files = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if "logs" in relative.parts or relative.as_posix() == "discovery_manifest.json":
            continue
        files[relative.as_posix()] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return files
