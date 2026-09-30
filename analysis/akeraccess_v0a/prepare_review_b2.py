#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare ÅkerAccess STOPPUNKT B2: eligible, carry-over visual QA.

Rules:
- minimum field area 1 ha
- exclude fields whose frozen ÅkerMinne 2025 dominant official crop name
  clearly denotes pasture/slåtteräng
- reuse legacy v0b human review; never commit it
- deterministically top up to target_per_status in each OSM evidence class
- preserve provenance: legacy labels are mechanically mapped, not silently
  treated as fresh B2 human labels
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from analysis.akeraccess_v0a.entry_discovery_v0a import discover_field_inputs, load_fields, slug

DEFAULT_WORK = ROOT / "work" / "akeraccess_v0a" / "sjobo"
DEFAULT_CONFIG = ROOT / "config" / "akeraccess_b2.json"
DEFAULT_AKERMINNE = Path(r"C:\AkerSync-Minne")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.casefold().split())


def deterministic_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_pasture_name(name: Any, tokens: list[str]) -> bool:
    text = norm_text(name)
    return bool(text) and any(norm_text(token) in text for token in tokens)


def legacy_qa_candidates(work: Path) -> list[Path]:
    name = "sjobo_akeraccess_visual_qa_v0b.csv"
    return [
        work / name,
        work / "review_v0b" / name,
        Path.home() / "Downloads" / name,
        Path.home() / "Nedladdningar" / name,
    ]


def find_legacy_qa(work: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise FileNotFoundError(p)
    for p in legacy_qa_candidates(work):
        if p.exists():
            return p
    raise FileNotFoundError(
        "Hittar inte sjobo_akeraccess_visual_qa_v0b.csv. "
        "Lägg den i Downloads/Nedladdningar eller ange --legacy-qa."
    )


def find_akerminne_2025(root: Path, municipality: str, field_ids: set[str]) -> tuple[pd.DataFrame, Path]:
    mun_root = root / "data" / "derived" / "akerminne_v1a" / "skane" / "municipalities"
    if not mun_root.exists():
        raise FileNotFoundError(f"ÅkerMinne municipality root missing: {mun_root}")
    candidates = sorted(mun_root.glob("*/akerminne_year_summary_classified.parquet"))
    best = None
    best_hits = -1
    best_path = None
    cols = [
        "municipality", "history_year", "current_field_id", "dominant_crop_name",
        "dominant_crop_known", "status",
    ]
    for p in candidates:
        try:
            frame = pd.read_parquet(p, columns=cols)
        except Exception:
            continue
        q = frame[pd.to_numeric(frame["history_year"], errors="coerce").eq(2025)].copy()
        if "municipality" in q.columns:
            names = q["municipality"].astype(str).map(norm_text)
            named = q[names.eq(norm_text(municipality))]
            if len(named):
                q = named
        hits = int(q["current_field_id"].astype(str).isin(field_ids).sum())
        if hits > best_hits:
            best, best_hits, best_path = q, hits, p
    if best is None or best_hits <= 0:
        raise RuntimeError(f"Could not match frozen ÅkerMinne 2025 summary to {municipality}")
    best = best.copy()
    best["field_id"] = best["current_field_id"].astype(str)
    best = best.drop_duplicates("field_id", keep="first")
    return best, best_path


ALT_HINT = re.compile(
    r"\b(rank|lila|gul punkt|andra kandidat|annan kandidat|inte basta|inte bästa|"
    r"rimligare|hellre|haller pa rank|håller på rank)\b",
    flags=re.IGNORECASE,
)


def map_legacy_label(label: Any, note: Any) -> tuple[str, str]:
    label = str(label or "").strip()
    note_text = str(note or "").strip()
    note_norm = norm_text(note_text)
    if "vaxthus" in note_norm:
        return "EXCLUDE_OTHER", "legacy_greenhouse_note"
    if label == "CORRECT_ENTRY":
        if ALT_HINT.search(note_text) or "inte cyan" in note_norm:
            return "OTHER_CANDIDATE_BETTER", "legacy_correct_with_alternative_note"
        return "RANK1_PLAUSIBLE", "legacy_correct"
    if label == "WRONG_ENTRY":
        if ALT_HINT.search(note_text) or any(x in note_norm for x in ("rank 2", "rank 5", "rank 6", "gul punkt")):
            return "OTHER_CANDIDATE_BETTER", "legacy_wrong_with_alternative_note"
        return "ACCESS_VISIBLE_NOT_CANDIDATE", "legacy_wrong"
    if label == "MISSED_ENTRY":
        return "ACCESS_VISIBLE_NOT_CANDIDATE", "legacy_missed"
    if label == "NO_VISIBLE_ENTRY":
        return "NO_VISIBLE_ACCESS", "legacy_no_visible"
    if label == "UNCLEAR":
        return "UNCLEAR", "legacy_unclear"
    return "", "legacy_unmapped"


def make_sample(
    summary: pd.DataFrame,
    legacy: pd.DataFrame,
    crop2025: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    min_area = float(cfg["minimum_area_ha"])
    target = int(cfg["target_per_status"])
    statuses = list(cfg["status_order"])
    pasture_tokens = [str(x) for x in cfg["pasture_name_tokens"]]

    base = summary.copy()
    base["field_id"] = base["field_id"].astype(str)
    base["area_ha"] = pd.to_numeric(base["area_ha"], errors="coerce")
    crop = crop2025[[
        "field_id", "dominant_crop_name", "dominant_crop_known", "status"
    ]].rename(columns={"status": "crop2025_status"}).copy()
    base = base.merge(crop, on="field_id", how="left", validate="one_to_one")
    base["crop2025_name"] = base["dominant_crop_name"].fillna("").astype(str)
    base["is_pasture_2025"] = base["crop2025_name"].map(
        lambda x: is_pasture_name(x, pasture_tokens)
    )
    base["eligible_area"] = base["area_ha"].ge(min_area)
    base["eligible_b2"] = base["eligible_area"] & ~base["is_pasture_2025"]
    base["eligibility_reason"] = "ELIGIBLE"
    base.loc[~base["eligible_area"], "eligibility_reason"] = "AREA_LT_1_HA"
    base.loc[base["eligible_area"] & base["is_pasture_2025"], "eligibility_reason"] = "PASTURE_2025"

    legacy = legacy.copy()
    required = {"field_id", "human_label", "note", "auto_status", "auto_confidence", "area_ha"}
    missing = sorted(required - set(legacy.columns))
    if missing:
        raise RuntimeError("Legacy QA missing columns: " + ", ".join(missing))
    legacy["field_id"] = legacy["field_id"].astype(str)
    legacy["legacy_label"] = legacy["human_label"].fillna("").astype(str)
    legacy["legacy_note"] = legacy["note"].fillna("").astype(str)
    mapped = [map_legacy_label(l, n) for l, n in zip(legacy["legacy_label"], legacy["legacy_note"])]
    legacy["initial_label"] = [x[0] for x in mapped]
    legacy["mapping_basis"] = [x[1] for x in mapped]
    legacy_keep = legacy[[
        "field_id", "legacy_label", "legacy_note", "initial_label", "mapping_basis"
    ]]

    base = base.merge(legacy_keep, on="field_id", how="left", validate="one_to_one")
    base["legacy_reviewed"] = base["legacy_label"].notna()
    for c in ["legacy_label", "legacy_note", "initial_label", "mapping_basis"]:
        base[c] = base[c].fillna("").astype(str)

    eligible = base[base["eligible_b2"]].copy()
    selected_parts = []
    selected_ids: set[str] = set()
    topup_counts: dict[str, int] = {}

    for status in statuses:
        q = eligible[eligible["entry_status"].eq(status)].copy()
        reviewed = q[q["legacy_reviewed"]].copy()
        reviewed["sample_source"] = "LEGACY_REUSED"
        reviewed["needs_review_b2"] = False
        reviewed["label_source"] = "legacy_mapped"
        selected_parts.append(reviewed)
        selected_ids.update(reviewed["field_id"].tolist())

        need = max(0, target - len(reviewed))
        pool = q[~q["field_id"].isin(selected_ids)].copy()
        pool["_hash"] = pool["field_id"].map(deterministic_hash)
        pool = pool.sort_values("_hash", kind="mergesort").head(need).drop(columns="_hash")
        pool["sample_source"] = "B2_TOPUP"
        pool["needs_review_b2"] = True
        pool["label_source"] = "new_b2"
        pool["initial_label"] = ""
        pool["mapping_basis"] = ""
        pool["legacy_label"] = ""
        pool["legacy_note"] = ""
        selected_parts.append(pool)
        selected_ids.update(pool["field_id"].tolist())
        topup_counts[status] = int(len(pool))

    sample = pd.concat(selected_parts, ignore_index=True)
    order = {s: i for i, s in enumerate(statuses)}
    sample["_status_order"] = sample["entry_status"].map(order)
    sample["_source_order"] = sample["sample_source"].map({"LEGACY_REUSED": 0, "B2_TOPUP": 1})
    sample["_hash"] = sample["field_id"].map(deterministic_hash)
    sample = sample.sort_values(
        ["_status_order", "_source_order", "_hash"], kind="mergesort"
    ).drop(columns=["_status_order", "_source_order", "_hash"]).reset_index(drop=True)
    sample["review_index_b2"] = range(1, len(sample) + 1)

    matched_pasture_names = (
        base.loc[base["is_pasture_2025"], "crop2025_name"]
        .value_counts().rename_axis("crop2025_name").reset_index(name="n_fields")
    )

    report = {
        "schema_version": cfg["schema_version"],
        "minimum_area_ha": min_area,
        "target_per_status": target,
        "population_fields": int(len(base)),
        "eligible_fields": int(base["eligible_b2"].sum()),
        "excluded_area_lt_1ha": int((~base["eligible_area"]).sum()),
        "excluded_pasture_2025": int((base["eligible_area"] & base["is_pasture_2025"]).sum()),
        "legacy_rows": int(len(legacy)),
        "legacy_reused_eligible": int(sample["sample_source"].eq("LEGACY_REUSED").sum()),
        "new_topup_fields": int(sample["sample_source"].eq("B2_TOPUP").sum()),
        "topup_by_status": topup_counts,
        "sample_by_status": {
            str(k): int(v) for k, v in sample["entry_status"].value_counts().to_dict().items()
        },
        "note": (
            "Legacy v0b labels are mechanically mapped and marked legacy_mapped. "
            "They remain distinguishable from fresh B2 human labels."
        ),
    }
    return sample, matched_pasture_names, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--legacy-qa", default=None)
    ap.add_argument("--akerminne-root", default=str(DEFAULT_AKERMINNE))
    args = ap.parse_args()

    work = Path(args.work)
    cfg = load_json(Path(args.config))
    summary_path = work / "sjobo_field_entry_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Run STOPPUNKT A first: {summary_path}")
    summary = pd.read_csv(summary_path, low_memory=False)
    legacy_path = find_legacy_qa(work, args.legacy_qa)
    legacy = pd.read_csv(legacy_path, encoding="utf-8-sig", low_memory=False)

    field_ids = set(summary["field_id"].astype(str))
    crop2025, crop_source = find_akerminne_2025(
        Path(args.akerminne_root), "Sjöbo", field_ids
    )
    sample, pasture_names, report = make_sample(summary, legacy, crop2025, cfg)

    out = work / "review_b2"
    out.mkdir(parents=True, exist_ok=True)
    sample_path = out / "sjobo_review_b2_sample.csv"
    pasture_path = out / "sjobo_review_b2_excluded_pasture_names.csv"
    report_path = out / "sjobo_review_b2_prepare.json"
    fields_path = out / "sjobo_review_b2_fields.geojson"

    sample.to_csv(sample_path, index=False, encoding="utf-8-sig")
    pasture_names.to_csv(pasture_path, index=False, encoding="utf-8-sig")

    blocks_path, skiften_path, local_cfg = discover_field_inputs()
    fields = load_fields("Sjöbo", blocks_path, skiften_path)
    fields = fields[fields["field_id"].isin(set(sample["field_id"]))].copy()
    attrs = sample[[
        "field_id", "entry_status", "best_confidence", "area_ha", "crop2025_name",
        "sample_source", "needs_review_b2", "initial_label", "legacy_label",
    ]].copy()
    fields = fields.drop(columns=["area_ha"], errors="ignore").merge(
        attrs, on="field_id", how="inner", validate="one_to_one"
    )
    fields.to_crs(4326).to_file(fields_path, driver="GeoJSON")

    report.update({
        "legacy_qa_source": str(legacy_path),
        "crop2025_source": str(crop_source),
        "field_geometry_config": str(local_cfg),
        "outputs": {
            "sample": str(sample_path),
            "fields_geojson": str(fields_path),
            "pasture_names": str(pasture_path),
        },
    })
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 96)
    print("ÅkerAccess STOPPUNKT B2 - ELIGIBILITY + QA CARRY-OVER")
    print("=" * 96)
    print(f"Legacy QA: {legacy_path}")
    print(f"ÅkerMinne 2025: {crop_source}")
    print(f"Population: {report['population_fields']:,}")
    print(f"Eligible B2 fields: {report['eligible_fields']:,}")
    print(f"Excluded <1 ha: {report['excluded_area_lt_1ha']:,}")
    print(f"Excluded pasture/slåtteräng (>=1 ha): {report['excluded_pasture_2025']:,}")
    if len(pasture_names):
        print("\nMATCHED PASTURE NAMES")
        print(pasture_names.to_string(index=False))
    print("\nB2 SAMPLE")
    print(sample.groupby(["entry_status", "sample_source"]).size().to_string())
    print(f"\nLegacy eligible reused: {report['legacy_reused_eligible']}")
    print(f"New fields requiring B2 review: {report['new_topup_fields']}")
    print(f"Sample: {sample_path}")
    print(f"Report: {report_path}")
    print("=" * 96)
    print("STOPPUNKT B2 PREPARE: PASS")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
