#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build municipality-lazy ÅkerFrö konservärt web sidecars from frozen C10 product.

This phase owns only:
  - data/akerfro/*
  - patched index.html (via separate UI patcher)

The ÅkerNorm base dist is copied and verified byte-for-byte outside those paths.
No ÅkerFrö model is recalculated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import traceback
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "akerfro-ertor-web-v0a"
INDEX_SCHEMA = "akerfro-ertor-web-index-v0a"
MANIFEST_SCHEMA = "akerfro-ertor-web-manifest-v0a"
EXPECTED_FIELDS = 128_636
EXPECTED_MUNICIPALITIES = 33
EXPECTED_CLASSES = {
    "A_STRONG_CANDIDATE": 7847,
    "B_PHYSICAL_CANDIDATE": 14882,
    "C_ROTATION_CAUTION": 1424,
    "D_NOT_HIGH_PHYSICAL_MATCH": 104483,
}
EXPECTED_BANDS = {"HIGH": 20327, "MEDIUM": 34060, "LOW": 74249}
OWNED_PREFIX = Path("data/akerfro")
OWNED_FILES = {
    Path("assets/akerfro_v0a.css"),
    Path("assets/akerfro_v0a.js"),
}

ROW_COLUMNS = [
    "class", "artmatch", "rotation_status", "predecessor_crop",
    "predecessor_prior", "predecessor_enrichment", "area_ha", "area_fit",
    "distance_bjuv_km", "bjuv_proximity", "area_logistics",
    "area_logistics_band", "priority_rank", "historical_positive",
    "last_conservart_year", "last_other_pea_year", "last_faba_year",
]
DICT_COLUMNS = {
    "class", "rotation_status", "predecessor_crop", "predecessor_prior",
    "area_logistics_band",
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_head() -> str:
    supplied = os.environ.get("AKERFRO_WEB_REPOSITORY_HEAD", "").strip()
    if supplied:
        return supplied
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def stable_json(document: Any, compact: bool = False) -> str:
    kwargs = {"ensure_ascii": False, "allow_nan": False}
    if compact:
        return json.dumps(document, separators=(",", ":"), **kwargs) + "\n"
    return json.dumps(document, indent=2, sort_keys=True, **kwargs) + "\n"


def atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if tmp.read_text(encoding="utf-8") != text:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Atomic write verification failed: {path}")
    os.replace(tmp, path)


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return "_".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in plain).split())


def is_owned(relative: Path) -> bool:
    return (
        relative == OWNED_PREFIX
        or OWNED_PREFIX in relative.parents
        or relative in OWNED_FILES
    )


def inventory(root: Path, *, exclude_owned: bool = False, exclude_index: bool = False) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root)
        if exclude_owned and is_owned(rel):
            continue
        if exclude_index and rel.as_posix() == "index.html":
            continue
        rows.append({"path": rel.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def verify_base_target(base_dist: Path, target_dist: Path) -> list[dict[str, Any]]:
    base = inventory(base_dist, exclude_owned=True, exclude_index=True)
    target = inventory(target_dist, exclude_owned=True, exclude_index=True)
    if base != target:
        bm = {row["path"]: row for row in base}
        tm = {row["path"]: row for row in target}
        changed = sorted(path for path in set(bm) | set(tm) if bm.get(path) != tm.get(path))
        raise RuntimeError(
            "Target dist differs from ÅkerNorm base outside index.html/data/akerfro: "
            + ", ".join(changed[:30])
        )
    return base


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def number(value: Any, digits: int | None = None) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    if digits is None:
        return x
    return round(x, digits)


def int_or_none(value: Any) -> int | None:
    x = number(value)
    return None if x is None else int(round(x))


def require_columns(frame: pd.DataFrame) -> None:
    required = {
        "current_field_id", "municipality", "artkandidat_class", "artmatch_score",
        "rotation_status", "crop_2025_name", "predecessor_prior",
        "predecessor_enrichment_ratio", "field_area_ha", "area_fit_score",
        "distance_bjuv_km", "bjuv_proximity_score", "area_logistics_score",
        "area_logistics_band", "operational_priority_rank", "is_positive",
        "last_conservart_any_component_year", "last_other_pea_clean_year",
        "last_faba_bean_clean_year",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError("Frozen C10 product missing web columns: " + ", ".join(missing))


def validate_frozen_product(frame: pd.DataFrame) -> None:
    require_columns(frame)
    if len(frame) != EXPECTED_FIELDS:
        raise RuntimeError(f"Expected {EXPECTED_FIELDS:,} fields, got {len(frame):,}")
    if frame["current_field_id"].duplicated().any():
        raise RuntimeError("Frozen C10 product has duplicate current_field_id")
    if frame["current_field_id"].isna().any():
        raise RuntimeError("Frozen C10 product has missing current_field_id")
    classes = {str(k): int(v) for k, v in frame["artkandidat_class"].value_counts().items()}
    if classes != EXPECTED_CLASSES:
        raise RuntimeError(f"Frozen C8b class anchors differ: {classes}")
    bands = {str(k): int(v) for k, v in frame["area_logistics_band"].value_counts().items()}
    if bands != EXPECTED_BANDS:
        raise RuntimeError(f"Frozen C10 operational-band anchors differ: {bands}")
    if frame["operational_priority_rank"].nunique() != EXPECTED_FIELDS:
        raise RuntimeError("Operational priority rank is not unique for all fields")
    if set(frame["operational_priority_rank"].astype(int)) != set(range(1, EXPECTED_FIELDS + 1)):
        raise RuntimeError("Operational priority rank is not a complete 1..N sequence")
    municipalities = sorted(frame["municipality"].dropna().astype(str).unique())
    if len(municipalities) != EXPECTED_MUNICIPALITIES:
        raise RuntimeError(f"Expected 33 municipalities, got {len(municipalities)}")
    for required_name in ("Kristianstad", "Skurup", "Lomma", "Trelleborg", "Helsingborg"):
        if required_name not in municipalities:
            raise RuntimeError(f"Expected municipality missing: {required_name}")


def make_dictionaries(frame: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    dictionaries: dict[str, list[str]] = {}
    indexes: dict[str, dict[str, int]] = {}
    sources = {
        "class": "artkandidat_class",
        "rotation_status": "rotation_status",
        "predecessor_crop": "crop_2025_name",
        "predecessor_prior": "predecessor_prior",
        "area_logistics_band": "area_logistics_band",
    }
    for target, source in sources.items():
        vals = sorted({clean_text(v) for v in frame[source]})
        dictionaries[target] = vals
        indexes[target] = {v: i for i, v in enumerate(vals)}
    return dictionaries, indexes


def pack_row(row: pd.Series, indexes: dict[str, dict[str, int]]) -> list[Any]:
    return [
        indexes["class"][clean_text(row["artkandidat_class"])],
        number(row["artmatch_score"], 2),
        indexes["rotation_status"][clean_text(row["rotation_status"])],
        indexes["predecessor_crop"][clean_text(row["crop_2025_name"])],
        indexes["predecessor_prior"][clean_text(row["predecessor_prior"])],
        number(row["predecessor_enrichment_ratio"], 3),
        number(row["field_area_ha"], 3),
        number(row["area_fit_score"], 1),
        number(row["distance_bjuv_km"], 2),
        number(row["bjuv_proximity_score"], 1),
        number(row["area_logistics_score"], 1),
        indexes["area_logistics_band"][clean_text(row["area_logistics_band"])],
        int(row["operational_priority_rank"]),
        bool(row["is_positive"]),
        int_or_none(row["last_conservart_any_component_year"]),
        int_or_none(row["last_other_pea_clean_year"]),
        int_or_none(row["last_faba_bean_clean_year"]),
    ]


def build_municipality_payload(group: pd.DataFrame) -> dict[str, Any]:
    municipality = str(group["municipality"].iloc[0])
    dictionaries, indexes = make_dictionaries(group)
    fields = {}
    for _, row in group.sort_values("current_field_id", kind="mergesort").iterrows():
        fields[str(row["current_field_id"])] = pack_row(row, indexes)
    counts = {str(k): int(v) for k, v in group["artkandidat_class"].value_counts().items()}
    return {
        "schema_version": SCHEMA,
        "municipality": municipality,
        "field_count": int(len(group)),
        "columns": ROW_COLUMNS,
        "dictionaries": dictionaries,
        "class_counts": counts,
        "fields": fields,
    }


def build_top1000(frame: pd.DataFrame) -> dict[str, Any]:
    q = frame.sort_values("operational_priority_rank", kind="mergesort").head(1000)
    rows = []
    for _, row in q.iterrows():
        field_id = str(row["current_field_id"])
        block, sep, skifte = field_id.partition("|")
        if not sep:
            raise RuntimeError(f"Malformed current_field_id in top 1000: {field_id}")
        rows.append({
            "rank": int(row["operational_priority_rank"]),
            "field_id": field_id,
            "block_id": block,
            "skifte_id": skifte,
            "municipality": str(row["municipality"]),
            "class": str(row["artkandidat_class"]),
            "artmatch": number(row["artmatch_score"], 2),
            "predecessor_crop": clean_text(row["crop_2025_name"]),
            "area_ha": number(row["field_area_ha"], 2),
            "distance_bjuv_km": number(row["distance_bjuv_km"], 1),
            "area_logistics": number(row["area_logistics_score"], 1),
        })
    return {
        "schema_version": "akerfro-ertor-toplist-v0a",
        "count": len(rows),
        "rows": rows,
    }


def build_data(frame: pd.DataFrame, destination: Path) -> dict[str, Any]:
    temp = destination.with_name(destination.name + ".tmp")
    backup = destination.with_name(destination.name + ".bak")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)

    entries = []
    total = 0
    for municipality, group in frame.groupby("municipality", sort=True):
        payload = build_municipality_payload(group)
        filename = f"{slug(municipality)}.json"
        path = temp / filename
        atomic_text(stable_json(payload, compact=True), path)
        entries.append({
            "municipality": str(municipality),
            "file": f"data/akerfro/{filename}",
            "fields": int(len(group)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "class_counts": payload["class_counts"],
        })
        total += len(group)

    if len(entries) != EXPECTED_MUNICIPALITIES or total != EXPECTED_FIELDS:
        raise RuntimeError(f"ÅkerFrö web partition totals differ: {len(entries)} / {total}")

    top_path = temp / "skane_top1000.json"
    atomic_text(stable_json(build_top1000(frame), compact=True), top_path)

    index = {
        "schema_version": INDEX_SCHEMA,
        "status": "PASS",
        "field_count": EXPECTED_FIELDS,
        "municipality_count": EXPECTED_MUNICIPALITIES,
        "class_counts": EXPECTED_CLASSES,
        "operational_band_counts": EXPECTED_BANDS,
        "toplist_file": "data/akerfro/skane_top1000.json",
        "toplist_count": 1000,
        "municipalities": entries,
    }
    atomic_text(stable_json(index), temp / "skane_index.json")

    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        os.replace(destination, backup)
    os.replace(temp, destination)
    if backup.exists():
        shutil.rmtree(backup)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dist", required=True, type=Path)
    parser.add_argument("--akerfro-product", required=True, type=Path)
    parser.add_argument("--dist", default=str(ROOT / "dist"), type=Path)
    parser.add_argument("--work", default=str(ROOT / "work/akerfro_web_v0a"), type=Path)
    parser.add_argument("--patcher", default=str(ROOT / "src/89_patch_akerfro_web_v0a_ui.py"), type=Path)
    args = parser.parse_args()

    base_dist = args.base_dist.resolve()
    product_path = args.akerfro_product.resolve()
    target_dist = args.dist.resolve()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    try:
        if base_dist == target_dist:
            raise RuntimeError("ÅkerNorm base dist and ÅkerFrö target dist must be different")
        if not (base_dist / "index.html").exists():
            raise RuntimeError(f"ÅkerNorm base index missing: {base_dist / 'index.html'}")
        base_html = (base_dist / "index.html").read_text(encoding="utf-8")
        if "AKERNORM_WEB_UI_V1" not in base_html:
            raise RuntimeError("Base dist is not the ÅkerNorm web version: AKERNORM_WEB_UI_V1 marker missing")
        if not (base_dist / "data/akernorm/skane_index.json").exists():
            raise RuntimeError("Base dist lacks data/akernorm/skane_index.json")
        if not product_path.exists():
            raise RuntimeError(f"Frozen ÅkerFrö C10 product missing: {product_path}")

        frame = pd.read_parquet(product_path)
        validate_frozen_product(frame)

        if not target_dist.exists():
            shutil.copytree(base_dist, target_dist)
        base_inventory = verify_base_target(base_dist, target_dist)

        index = build_data(frame, target_dist / OWNED_PREFIX)

        assets_dir = target_dist / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        for name in ("akerfro_v0a.css", "akerfro_v0a.js"):
            source = ROOT / "web" / name
            if not source.exists():
                raise RuntimeError(f"ÅkerFrö web asset missing: {source}")
            shutil.copy2(source, assets_dir / name)

        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("akerfro_web_ui", args.patcher.resolve())
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load UI patcher: {args.patcher}")
        patcher = module_from_spec(spec)
        spec.loader.exec_module(patcher)

        source_html = (base_dist / "index.html").read_text(encoding="utf-8")
        mapping = {str(row["municipality"]): str(row["file"]) for row in index["municipalities"]}
        patched = patcher.patch_html(source_html, mapping, index["toplist_file"])
        atomic_text(patched, target_dist / "index.html")
        verify_base_target(base_dist, target_dist)

        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "status": "PASS",
            "repository_head": repository_head(),
            "base_dist": str(base_dist),
            "target_dist": str(target_dist),
            "akerfro_product": str(product_path),
            "akerfro_product_sha256": sha256_file(product_path),
            "base_index_sha256": sha256_file(base_dist / "index.html"),
            "patched_index_sha256": sha256_file(target_dist / "index.html"),
            "protected_base_files": base_inventory,
            "municipality_count": index["municipality_count"],
            "field_count": index["field_count"],
            "class_counts": index["class_counts"],
            "operational_band_counts": index["operational_band_counts"],
            "web_artifacts": (
                inventory(target_dist / OWNED_PREFIX)
                + [
                    {"path": path.as_posix(), "bytes": (target_dist / path).stat().st_size,
                     "sha256": sha256_file(target_dist / path)}
                    for path in sorted(OWNED_FILES, key=lambda p: p.as_posix())
                ]
            ),
            "scope": {
                "akerfro_model_recalculated": False,
                "akernorm_base_changed": False,
                "deployment": False,
            },
        }
        manifest["manifest_id"] = "akerfro-web-" + hashlib.sha256(
            stable_json({k: v for k, v in manifest.items() if k != "manifest_id"}).encode("utf-8")
        ).hexdigest()[:16]
        atomic_text(stable_json(manifest), work / "akerfro_web_manifest.json")

        print("=" * 92)
        print("ÅkerFrö – Ärter MVP v0a WEB DATA + UI BUILD: PASS")
        print("=" * 92)
        print(f"Base: {base_dist}")
        print(f"Target: {target_dist}")
        print(f"Fields: {index['field_count']:,} · municipalities: {index['municipality_count']}")
        print(f"A/B/C/D: {index['class_counts']}")
        print("ÅkerNorm base files: byte-identical outside index.html / data/akerfro / ÅkerFrö assets")
        print("Frozen ÅkerFrö model recalculated: NO")
        print("Deployment: NO")
        print("=" * 92)
        return 0
    except Exception as exc:
        (logs / "build_traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"ÅkerFrö WEB BUILD: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
