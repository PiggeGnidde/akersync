#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

STATUS_VERSION = "akerminne-status-v1a-r1"


@dataclass(frozen=True)
class HistoryStatusConfig:
    minimum_match_coverage: float = 0.01
    complete_coverage_min: float = 0.95
    mixed_secondary_crop_min_share: float = 0.05
    web_component_min_share: float = 0.01
    overlap_raw_tolerance: float = 0.000001
    material_overlap_excess: float = 0.005

    def validate(self) -> None:
        vals = {
            "minimum_match_coverage": self.minimum_match_coverage,
            "complete_coverage_min": self.complete_coverage_min,
            "mixed_secondary_crop_min_share": self.mixed_secondary_crop_min_share,
            "web_component_min_share": self.web_component_min_share,
            "overlap_raw_tolerance": self.overlap_raw_tolerance,
            "material_overlap_excess": self.material_overlap_excess,
        }
        for name, value in vals.items():
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be in [0,1], got {value}")
        if self.minimum_match_coverage > self.complete_coverage_min:
            raise ValueError("minimum_match_coverage must be <= complete_coverage_min")
        if self.web_component_min_share > self.mixed_secondary_crop_min_share:
            raise ValueError("web_component_min_share must be <= mixed_secondary_crop_min_share")

    @classmethod
    def from_dict(cls, cfg: dict) -> "HistoryStatusConfig":
        out = cls(
            minimum_match_coverage=float(cfg.get("minimum_match_coverage", 0.01)),
            complete_coverage_min=float(cfg.get("complete_coverage_min", 0.95)),
            mixed_secondary_crop_min_share=float(cfg.get("mixed_secondary_crop_min_share", 0.05)),
            web_component_min_share=float(cfg.get("web_component_min_share", 0.01)),
            overlap_raw_tolerance=float(cfg.get("overlap_raw_tolerance", 0.000001)),
            material_overlap_excess=float(cfg.get("material_overlap_excess", 0.005)),
        )
        out.validate()
        return out


def grouped_crop_areas(summary: pd.DataFrame, components: pd.DataFrame) -> pd.DataFrame:
    """Group raw polygon fragments by year/current field/raw crop tuple.

    Raw component rows remain untouched elsewhere; this derived table is only
    for deterministic status/web decisions so multiple fragments of the same
    crop are not mistaken for mixed cropping.
    """
    required_s = {"history_year", "current_field_id", "current_area_m2"}
    required_c = {
        "history_year", "current_field_id", "crop_code_raw",
        "crop_subcategory_raw", "intersection_m2",
    }
    ms = sorted(required_s - set(summary.columns))
    if ms:
        raise ValueError(f"summary missing columns {ms}")
    if components.empty:
        return pd.DataFrame(columns=[
            "history_year", "current_field_id", "crop_code_raw", "crop_subcategory_raw",
            "crop_area_m2", "current_area_m2", "crop_share_current", "crop_rank",
        ])
    mc = sorted(required_c - set(components.columns))
    if mc:
        raise ValueError(f"components missing columns {mc}")

    x = components.copy()
    x["_code"] = x["crop_code_raw"].fillna("<NULL>").astype(str)
    x["_sub"] = x["crop_subcategory_raw"].fillna("<NULL>").astype(str)
    grouped = (
        x.groupby(["history_year", "current_field_id", "_code", "_sub"], as_index=False, sort=False)["intersection_m2"]
        .sum()
        .rename(columns={"intersection_m2": "crop_area_m2"})
    )
    area = summary[["history_year", "current_field_id", "current_area_m2"]].drop_duplicates()
    grouped = grouped.merge(area, on=["history_year", "current_field_id"], how="left", validate="many_to_one")
    if grouped["current_area_m2"].isna().any():
        raise RuntimeError("crop grouping could not resolve current_area_m2")
    grouped["crop_share_current"] = grouped["crop_area_m2"] / grouped["current_area_m2"]
    grouped = grouped.sort_values(
        ["history_year", "current_field_id", "crop_share_current", "_code", "_sub"],
        ascending=[True, True, False, True, True], kind="mergesort",
    ).reset_index(drop=True)
    grouped["crop_rank"] = grouped.groupby(["history_year", "current_field_id"]).cumcount() + 1
    grouped["crop_code_raw"] = grouped["_code"].replace({"<NULL>": None})
    grouped["crop_subcategory_raw"] = grouped["_sub"].replace({"<NULL>": None})
    return grouped.drop(columns=["_code", "_sub"])


def apply_history_status(
    summary: pd.DataFrame,
    components: pd.DataFrame,
    cfg: HistoryStatusConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = cfg or HistoryStatusConfig()
    cfg.validate()
    out = summary.copy()
    crops = grouped_crop_areas(out, components)

    first = crops[crops["crop_rank"] == 1][["history_year", "current_field_id", "crop_share_current"]].rename(
        columns={"crop_share_current": "first_crop_share_grouped"}
    )
    second = crops[crops["crop_rank"] == 2][["history_year", "current_field_id", "crop_share_current"]].rename(
        columns={"crop_share_current": "second_crop_share"}
    )
    visible = (
        crops[crops["crop_share_current"] >= cfg.web_component_min_share]
        .groupby(["history_year", "current_field_id"]).size().rename("significant_crop_count").reset_index()
        if len(crops) else pd.DataFrame(columns=["history_year", "current_field_id", "significant_crop_count"])
    )
    for frame in (first, second, visible):
        out = out.merge(frame, on=["history_year", "current_field_id"], how="left", validate="one_to_one")
    out["first_crop_share_grouped"] = pd.to_numeric(out["first_crop_share_grouped"], errors="coerce").fillna(0.0)
    out["second_crop_share"] = pd.to_numeric(out["second_crop_share"], errors="coerce").fillna(0.0)
    out["significant_crop_count"] = pd.to_numeric(out["significant_crop_count"], errors="coerce").fillna(0).astype(int)

    statuses: list[str] = []
    reason_out: list[str] = []
    material_overlap: list[bool] = []
    for row in out.itertuples(index=False):
        raw = float(row.coverage_raw)
        display = float(row.coverage_display)
        second_share = float(row.second_crop_share)
        flags = [f for f in str(getattr(row, "reason_flags", "") or "").split(";") if f]
        if display < cfg.minimum_match_coverage:
            status = "NO_PUBLIC_MATCH"
            if raw > 0.0 and "BELOW_MIN_MATCH_COVERAGE" not in flags:
                flags.append("BELOW_MIN_MATCH_COVERAGE")
        elif display < cfg.complete_coverage_min:
            status = "PARTIAL_COVERAGE"
            if "LOW_COVERAGE" not in flags:
                flags.append("LOW_COVERAGE")
        elif second_share >= cfg.mixed_secondary_crop_min_share:
            status = "MIXED_CROPS"
            if "MULTIPLE_CROPS" not in flags:
                flags.append("MULTIPLE_CROPS")
        else:
            status = "SINGLE_CROP"
        excess = max(raw - 1.0, 0.0)
        material = excess > cfg.material_overlap_excess
        # Preserve DUPLICATE_OVERLAP from raw QA. Do not let microscopic overlaps
        # replace the agronomic/coverage status; materiality is a separate QA field.
        if raw > 1.0 + cfg.overlap_raw_tolerance and "DUPLICATE_OVERLAP" not in flags:
            flags.append("DUPLICATE_OVERLAP")
        statuses.append(status)
        reason_out.append(";".join(flags))
        material_overlap.append(material)

    out["status"] = statuses
    out["reason_flags"] = reason_out
    out["overlap_excess_raw"] = (out["coverage_raw"].astype(float) - 1.0).clip(lower=0.0)
    out["material_overlap_anomaly"] = material_overlap
    out["status_version"] = STATUS_VERSION
    return out, crops
