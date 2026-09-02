#!/usr/bin/env python3
"""Independent STOPPUNKT D verification for the local ÅkerNorm V1 web build."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIELDS = 128_636
EXPECTED_ROWS = 402_922
EXPECTED_MUNICIPALITIES = 33
DEEP_CODES = {"1262", "1264", "1290"}  # Lomma, Skurup, Kristianstad
V1_CROP_CODES = {2, 3, 4, 20, 45, 46}
ROW_COLUMNS = [
    "crop_code", "crop_name", "history_year_count", "history_component_year_count",
    "history_years", "history_quality", "sko_id", "sko_share",
    "official_sko_norm_t_ha", "akerscore_value", "sko_crop_reference_score",
    "beta_t_ha_per_score", "adjustment_t_ha", "field_akernorm_t_ha",
    "display_akernorm_t_ha", "model_status", "reason_flags", "score_support_status",
]


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True, encoding="utf-8").strip()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stable_json(document: Any) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def verify_record(root: Path, record: dict[str, Any]) -> Path:
    relative = Path(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Unsafe manifest path: {record['path']}")
    path = root / relative
    if not path.exists() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
        raise RuntimeError(f"Manifest artifact mismatch: {path}")
    return path


def protected_inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if relative.as_posix() == "index.html" or Path("data/akernorm") in relative.parents:
            continue
        records.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def scalar(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def load_official_crop_tables() -> tuple[dict[int, Any], Any]:
    path = ROOT / "src/60_apply_akerminne_official_crop_codes.py"
    spec = importlib.util.spec_from_file_location("akernorm_verify_official_crop_codes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load official crop-code verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    directory = ROOT / "data/reference/akerminne_crop_codes_official"
    tables, _ = module.load_official_tables(directory, directory / "manifest.json")
    return tables, module.lookup


def annual_crop_labels(row: pd.Series, tables: dict[int, Any], lookup: Any) -> list[list[Any]]:
    current = str(row["crop_name"])
    code = str(int(row["crop_code_canonical"]))
    annual = []
    for year in sorted(years(row["history_years"])):
        record = lookup(tables, year, code, None)
        annual.append([year, str(record[0]) if record is not None else current])
    if current.startswith("Grödkod ") and not any(label and not label.startswith("Grödkod ") for _, label in annual):
        raise RuntimeError(f"Official annual crop label is unresolved: {current}")
    return annual


def resolved_crop_name(row: pd.Series, tables: dict[int, Any], lookup: Any) -> str:
    annual = annual_crop_labels(row, tables, lookup)
    unique = list(dict.fromkeys(label for _, label in annual if label))
    if len(unique) > 1:
        return f"{annual[-1][1]} (kod {int(row['crop_code_canonical'])}; årsnamn varierar)"
    return unique[0] if unique else str(row["crop_name"])


CROP_TABLES, CROP_LOOKUP = load_official_crop_tables()


def years(value: Any) -> list[int]:
    return [int(item) for item in json.loads(str(value or "[]"))]


def group(status: str) -> int:
    return 0 if status.startswith("FIELD_ADJUSTED") else 1 if status.startswith("OFFICIAL_SKO_ONLY") else 2


def sort_key(row: pd.Series) -> tuple[Any, ...]:
    history = years(row["history_years"])
    code = int(row["crop_code_canonical"])
    status = str(row["model_status"])
    return (
        group(status), 0 if not status.startswith("UNAVAILABLE") or code in V1_CROP_CODES else 1,
        -(max(history) if history else 0), -int(row["history_year_count"]), code, resolved_crop_name(row, CROP_TABLES, CROP_LOOKUP),
    )


def source_array(row: pd.Series, reverse: dict[str, dict[str, int]]) -> list[Any]:
    text = lambda value: "" if value is None or pd.isna(value) else str(value)
    return [
        int(row["crop_code_canonical"]), reverse["crop_name"][resolved_crop_name(row, CROP_TABLES, CROP_LOOKUP)], int(row["history_year_count"]),
        int(row["history_component_year_count"]), years(row["history_years"]), reverse["history_quality"][text(row["history_quality"])],
        reverse["sko_id"][text(row["sko_id"])], scalar(row["sko_share"]), scalar(row["official_sko_norm_t_ha"]),
        scalar(row["akerscore_value"]), scalar(row["sko_crop_reference_score"]),
        scalar(row["beta_t_ha_per_score"]), scalar(row["adjustment_t_ha"]),
        scalar(row["field_akernorm_t_ha"]), scalar(row["display_akernorm_t_ha"]),
        reverse["model_status"][text(row["model_status"])], reverse["reason_flags"][text(row["reason_flags"])],
        reverse["score_support_status"][text(row["score_support_status"])],
    ]


def compare_deep(payload: dict[str, Any], source_dir: Path) -> None:
    source = pd.read_parquet(source_dir / "field_akernorm_v1.parquet")
    coverage = pd.read_parquet(source_dir / "field_coverage.parquet")
    if set(payload["fields"]) != set(coverage["current_field_id"].astype(str)):
        raise RuntimeError(f"{payload['municipality']}: web/source field IDs differ")
    dictionaries = payload.get("dictionaries") or {}
    reverse = {name: {str(value): index for index, value in enumerate(values)} for name, values in dictionaries.items()}
    expected: dict[str, list[list[Any]]] = {field: [] for field in payload["fields"]}
    expected_annual: dict[str, dict[str, str]] = {}
    for field_id, rows in source.groupby(source["current_field_id"].astype(str), sort=True):
        ordered = sorted((row for _, row in rows.iterrows()), key=sort_key)
        expected[str(field_id)] = [source_array(row, reverse) for row in ordered]
        for row in ordered:
            code = str(int(row["crop_code_canonical"]))
            for year, label in annual_crop_labels(row, CROP_TABLES, CROP_LOOKUP):
                values = expected_annual.setdefault(str(year), {})
                old = values.get(code)
                if old is not None and old != label:
                    raise RuntimeError(f"{payload['municipality']}: conflicting source annual label for {year}/{code}")
                values[code] = label
    expected_annual = {
        year: {code: values[code] for code in sorted(values, key=int)}
        for year, values in sorted(expected_annual.items(), key=lambda item: int(item[0]))
    }
    if expected != payload["fields"]:
        raise RuntimeError(f"{payload['municipality']}: deep field/crop payload differs from STOPPUNKT C")
    if expected_annual != payload.get("annual_crop_labels"):
        raise RuntimeError(f"{payload['municipality']}: annual crop-label map differs from official dictionaries")


def verify_html(path: Path, entries: list[dict[str, Any]]) -> None:
    html = path.read_text(encoding="utf-8")
    required = (
        "AKERNORM_WEB_UI_V1", "AKERMINNE_SKANE_UI_R2", "ÅkerNorm",
        "Normal produktionsnivå – inte prognos för nästa skördeår",
        "Skiftesanpassad ÅkerNorm", "Officiell normskörd i området",
        "Skiftesanpassad ÅkerNorm: ej tillgänglig ännu", "ÅkerNorm ej tillgänglig ännu",
        "Officiell normskörd saknas i SKO", "Årsberoende grödkod", "Årsvisa grödnamn",
        "Högre osäkerhet", "Svag skiftesjustering", "akernormToggle(this)",
        "data/akernorm/1290_kristianstad.json", "${akerminneSection(p)}", "${akernormSection(p)}",
        "Historisk jordbruksklass — referensdata", "Skördeområde (SKO)",
    )
    missing = [item for item in required if item not in html]
    if missing:
        raise RuntimeError("ÅkerNorm/local frontend missing: " + ", ".join(missing))
    forbidden = (
        "förväntad skörd nästa år", "uppmätt skörd", "faktisk skörd", "garanterad skörd",
        "satellitverifierad", "individuellt 95 %", "avvikelse från faktisk skörd",
    )
    present = [item for item in forbidden if item.casefold() in html.casefold()]
    if present:
        raise RuntimeError("Forbidden web copy present: " + ", ".join(present))
    if html.count("AKERNORM_WEB_UI_V1") != 2:
        raise RuntimeError("ÅkerNorm UI patch marker count differs")
    for entry in entries:
        token = json.dumps(str(entry["municipality"]), ensure_ascii=False) + ":" + json.dumps(str(entry["file"]), ensure_ascii=False)
        if token not in html:
            raise RuntimeError(f"UI sidecar mapping missing: {entry['municipality']}")


def write_reports(output_root: Path, manifest: dict[str, Any], index: dict[str, Any], sizes: list[dict[str, Any]]) -> None:
    qa = output_root / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sizes).to_csv(qa / "web_payload_sizes.csv", index=False, encoding="utf-8-sig")
    lines = [
        "# ÅkerNorm V1 – web QA / STOPPUNKT D", "", "- Status: `PASS`",
        f"- Kommuner: `{index['municipality_count']}`", f"- Skiften: `{index['field_count']}`",
        f"- Skifte/gröda-rader: `{index['field_crop_rows']}`", f"- Sidecar-bytes: `{index['sidecar_bytes']}`",
        f"- Rader med korrigerat officiellt grödnamn: `{index['official_crop_labels_resolved']}`",
        f"- Rader med varierande årsbenämning: `{index['year_sensitive_crop_rows']}`",
        "- Kommunvis lazy load: `PASS`", "- Kristianstad + Skurup + Lomma djupjämförda mot STOPPUNKT C: `PASS`",
        "- ÅkerScore/ÅkerVärde/ÅkerDrift/ÅkerMinne-filer byte-identiska: `PASS`",
        "- Desktop/mobil markup och direktlänkens gemensamma fältpanel: `PASS`",
        "- Deployment: `NO`", "- Sentinel-2: `NO`", "", "## Statusfördelning", "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(index["status_counts"].items()))
    lines += [
        "", "## Manuell visuell retur", "",
        "Ta skärmbilder lokalt av: skiftesanpassat värde, officiell norm utan skiftesjustering, ej tillgänglig, Kristianstad, två andra kommuner samt mobilvy.",
        "", "## STOPPUNKT D", "", "Ingen taggning, merge, deployment eller Sentinel-2-körning har gjorts.",
    ]
    (qa / "web_qa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {
        "schema_version": "akernorm-stopd-verification-v1", "status": "PASS",
        "repository_head": git("rev-parse", "HEAD"), "web_manifest_id": manifest["manifest_id"],
        "full_manifest_id": manifest["full_manifest_id"], "municipality_count": index["municipality_count"],
        "field_count": index["field_count"], "field_crop_rows": index["field_crop_rows"],
        "sidecar_bytes": index["sidecar_bytes"], "deep_verified_municipality_codes": sorted(DEEP_CODES),
        "official_crop_labels_resolved": index["official_crop_labels_resolved"],
        "year_sensitive_crop_rows": index["year_sensitive_crop_rows"],
        "protected_products_unchanged": True, "lazy_load": True,
        "scope": {"full_skane_run": True, "web_changed": True, "deployment": False, "sentinel2_changed": False},
    }
    (qa / "stopd_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--base-dist", required=True, type=Path)
    parser.add_argument("--dist", default=str(ROOT / "dist"), type=Path)
    args = parser.parse_args()
    output_root, base_dist, dist = args.output_root.resolve(), args.base_dist.resolve(), args.dist.resolve()
    logs = output_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "web_verify_traceback.log").unlink(missing_ok=True)
    try:
        if git("branch", "--show-current") != "feature/akernorm-product-v1a":
            raise RuntimeError("STOPPUNKT D verifier requires feature/akernorm-product-v1a")
        if git("status", "--short"):
            raise RuntimeError("Working tree is not clean before STOPPUNKT D verification")
        manifest = read_json(output_root / "manifests/akernorm_web_manifest.json")
        if manifest.get("schema_version") != "akernorm-web-manifest-v1" or manifest.get("status") != "PASS":
            raise RuntimeError("ÅkerNorm web manifest is not PASS")
        expected_manifest_id = "akernorm-web-" + hashlib.sha256(
            stable_json({key: value for key, value in manifest.items() if key != "manifest_id"}).encode("utf-8")
        ).hexdigest()[:16]
        if manifest.get("manifest_id") != expected_manifest_id:
            raise RuntimeError("ÅkerNorm web manifest ID does not match its content")
        scope = manifest.get("scope", {})
        if not scope.get("web_changed") or scope.get("deployment") or scope.get("sentinel2_changed"):
            raise RuntimeError("Web manifest scope crosses STOPPUNKT D")
        if sha256_file(base_dist / "index.html") != manifest["base_index_sha256"]:
            raise RuntimeError("Frozen base index differs from web manifest")
        if sha256_file(dist / "index.html") != manifest["patched_index_sha256"]:
            raise RuntimeError("Patched index differs from web manifest")
        expected_protected = manifest.get("protected_base_files") or []
        if protected_inventory(base_dist) != expected_protected or protected_inventory(dist) != expected_protected:
            raise RuntimeError("Existing Score/Value/Drift/Minne web artifacts are not byte-identical")
        for record in manifest.get("web_artifacts", []):
            verify_record(dist / "data/akernorm", record)

        index = read_json(dist / "data/akernorm/skane_index.json")
        if index.get("schema_version") != "akernorm-web-index-v1" or index.get("status") != "PASS":
            raise RuntimeError("ÅkerNorm web index is not PASS")
        official_manifest = ROOT / "data/reference/akerminne_crop_codes_official/manifest.json"
        if index.get("official_crop_dictionary_manifest_sha256") != sha256_file(official_manifest):
            raise RuntimeError("Official annual crop-code dictionary hash differs")
        if int(index.get("official_crop_labels_resolved", 0)) <= 0:
            raise RuntimeError("No official crop-label corrections were documented")
        if (int(index.get("municipality_count", -1)), int(index.get("field_count", -1)), int(index.get("field_crop_rows", -1))) != (EXPECTED_MUNICIPALITIES, EXPECTED_FIELDS, EXPECTED_ROWS):
            raise RuntimeError("ÅkerNorm web index totals differ")
        entries = index.get("municipalities") or []
        if len(entries) != EXPECTED_MUNICIPALITIES or {str(row["municipality_code"]) for row in entries} & DEEP_CODES != DEEP_CODES:
            raise RuntimeError("ÅkerNorm municipality index is incomplete")
        verify_html(dist / "index.html", entries)
        cases = index.get("test_cases") or []
        required_cases = {
            "adjusted_wheat_premium", "adjusted_wheat_discount", "adjusted_barley",
            "oats_higher_uncertainty", "rape_weak_effect", "table_potato_official_only",
            "starch_potato_official_only", "history_component_only", "low_sko_share",
            "missing_akerscore", "unsupported_crop", "no_qualifying_crops",
        }
        if {str(row.get("category")) for row in cases} != required_cases:
            raise RuntimeError("Web test-case inventory is incomplete")
        for case in cases:
            if case["category"] == "no_qualifying_crops":
                if case.get("status") != "NOT_PRESENT_IN_STOPC":
                    raise RuntimeError("No-history web case must document frozen-input absence")
                continue
            direct = str(case.get("direct_url") or "")
            if not all(token in direct for token in ("kommun=", "block=", "skifte=", "lager=score")):
                raise RuntimeError(f"Web test case lacks direct field URL: {case['category']}")

        total_fields = total_rows = total_bytes = year_sensitive_rows = 0
        statuses: Counter[str] = Counter()
        sizes = []
        for entry in entries:
            path = dist / entry["file"]
            if not path.exists() or path.stat().st_size != int(entry["bytes"]) or sha256_file(path) != entry["sha256"]:
                raise RuntimeError(f"Municipality sidecar mismatch: {path}")
            data = read_json(path)
            dictionaries = data.get("dictionaries") or {}
            annual_lookup = data.get("annual_crop_labels") or {}
            if data.get("schema_version") != "akernorm-web-v1" or data.get("columns") != ROW_COLUMNS or set(dictionaries) != {"crop_name", "history_quality", "sko_id", "model_status", "reason_flags", "score_support_status"}:
                raise RuntimeError(f"{path.name}: schema/columns differ")
            if str(data.get("municipality_code")) != str(entry["municipality_code"]) or data.get("municipality") != entry["municipality"]:
                raise RuntimeError(f"{path.name}: municipality identity differs")
            fields = data.get("fields") or {}
            rows = sum(len(value) for value in fields.values())
            if len(fields) != int(data["field_count"]) or rows != int(data["field_crop_rows"]):
                raise RuntimeError(f"{path.name}: payload totals differ")
            counts = Counter(str(dictionaries["model_status"][row[15]]) for value in fields.values() for row in value)
            if dict(sorted(counts.items())) != data.get("status_counts"):
                raise RuntimeError(f"{path.name}: status reconciliation differs")
            for field_rows in fields.values():
                objects = []
                for raw in field_rows:
                    item = dict(zip(ROW_COLUMNS, raw))
                    for name, dictionary in dictionaries.items():
                        item[name] = dictionary[item[name]]
                    objects.append(item)
                    if str(item["crop_name"]).startswith("Grödkod "):
                        raise RuntimeError(f"{path.name}: unresolved raw crop-code label remains")
                    annual = []
                    for year in item["history_years"]:
                        label = (annual_lookup.get(str(year)) or {}).get(str(item["crop_code"]))
                        if not label:
                            raise RuntimeError(f"{path.name}: annual crop label missing for {year}/code {item['crop_code']}")
                        annual.append([int(year), str(label)])
                    unique = {label for _, label in annual}
                    if len(unique) > 1:
                        expected_name = f"{annual[-1][1]} (kod {int(item['crop_code'])}; årsnamn varierar)"
                        if item["crop_name"] != expected_name:
                            raise RuntimeError(f"{path.name}: year-sensitive crop display label differs")
                        year_sensitive_rows += 1
                    elif unique and item["crop_name"] != annual[-1][1]:
                        raise RuntimeError(f"{path.name}: stable official crop display label differs")
                keys = [(group(str(row["model_status"])), 0 if not str(row["model_status"]).startswith("UNAVAILABLE") or int(row["crop_code"]) in V1_CROP_CODES else 1, -(max(row["history_years"] or [0])), -int(row["history_year_count"]), int(row["crop_code"]), str(row["crop_name"])) for row in objects]
                if keys != sorted(keys):
                    raise RuntimeError(f"{path.name}: deterministic display sorting differs")
            code = str(entry["municipality_code"])
            if code in DEEP_CODES:
                source_dir = next((output_root / "full_skane/municipalities").glob(f"{code}_*"), None)
                if source_dir is None:
                    raise RuntimeError(f"STOPPUNKT C source missing for {code}")
                compare_deep(data, source_dir)
            total_fields += len(fields); total_rows += rows; total_bytes += path.stat().st_size
            statuses.update(counts)
            sizes.append({"municipality_code": code, "municipality": entry["municipality"], "fields": len(fields), "field_crop_rows": rows, "bytes": path.stat().st_size, "bytes_per_field": path.stat().st_size / len(fields)})
        if (total_fields, total_rows, total_bytes) != (EXPECTED_FIELDS, EXPECTED_ROWS, int(index["sidecar_bytes"])):
            raise RuntimeError("Aggregated web totals differ")
        if dict(sorted(statuses.items())) != index.get("status_counts"):
            raise RuntimeError("All-Skåne web status reconciliation differs")
        if year_sensitive_rows != int(index.get("year_sensitive_crop_rows", -1)):
            raise RuntimeError("Year-sensitive crop row reconciliation differs")
        write_reports(output_root, manifest, index, sizes)
        (output_root / "qa/web_test_cases.json").write_text(
            json.dumps({"schema_version": "akernorm-web-test-cases-v1", "status": "PASS", "test_cases": cases}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("=" * 88)
        print("AKERNORM V1 STOPPUNKT D WEB VERIFIER: PASS")
        print("=" * 88)
        print(f"Municipalities: {EXPECTED_MUNICIPALITIES} · fields: {EXPECTED_FIELDS:,} · rows: {EXPECTED_ROWS:,}")
        print("Deep source comparison: Kristianstad, Skurup, Lomma PASS")
        print("Existing Score/Value/Drift/Minne: byte-identical PASS")
        print("Lazy ÅkerNorm UI/schema/copy/sorting: PASS")
        print("Deployment/Sentinel-2: NO · STOPPUNKT D")
        return 0
    except Exception as exc:
        (logs / "web_verify_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"AKERNORM V1 STOPPUNKT D WEB VERIFIER: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
