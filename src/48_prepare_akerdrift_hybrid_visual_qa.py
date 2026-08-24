#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a bounded, deterministic visual review list for Hybrid RC1.

The output links directly to a field in the local ÅkerPass map.  It does not
change scores and is intended as the final manual gate before publication.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "derived" / "akerdrift_fast_v2_hybrid_rc1" / "akerdrift_fast_v2_hybrid_rc1_skane.parquet"
DEFAULT_MODEL = ROOT / "config" / "akerdrift_fast_v2_routecal_rc0.json"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "akerdrift_fast_v2_hybrid_rc1" / "qa"
MAX_REVIEW_ROWS = 50
MIN_REVIEW_ROWS = 40


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    features = pd.DataFrame(index=frame.index)
    features["fast_geometry_score"] = _number(frame, "fast_v1_geometry_score")
    features["log_area_ha"] = np.log(_number(frame, "area_ha").where(_number(frame, "area_ha") > 0))
    features["rectangularity"] = _number(frame, "rectangularity")
    features["compactness"] = _number(frame, "compactness")
    features["log_erl_m"] = np.log(_number(frame, "erl").where(_number(frame, "erl") > 0))
    return features


def select_review_rows(frame: pd.DataFrame, config: dict, limit: int = MAX_REVIEW_ROWS) -> pd.DataFrame:
    required = {
        "kommun", "block_id", "skifte_id", "area_ha", "hole_count",
        "fast_v1_akerdrift_score", "akerdrift_score", "score_delta_hybrid_minus_v1",
        "fast_v1_geometry_score", "rectangularity", "compactness", "erl",
        "drift_score_source",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Hybridfilen saknar kolumner: " + ", ".join(missing))
    scored = frame.dropna(subset=["akerdrift_score", "fast_v1_akerdrift_score"]).copy()
    scored["field_key"] = scored["block_id"].astype(str) + "|" + scored["skifte_id"].astype(str)
    if scored["field_key"].duplicated().any():
        raise ValueError("Hybridfilen innehåller dubbla skiftesnycklar")
    scored["absolute_delta"] = _number(scored, "score_delta_hybrid_minus_v1").abs()
    features = feature_frame(scored)
    ranges = config["geometry_model"]["clip_ranges"]

    selected: dict[str, dict] = {}

    def add(part: pd.DataFrame, category: str, reason: str, count: int) -> None:
        for index, row in part.head(count).iterrows():
            key = str(row["field_key"])
            if key in selected or len(selected) >= limit:
                continue
            payload = row.to_dict()
            payload["qa_category"] = category
            payload["qa_reason"] = reason
            selected[key] = payload

    delta = _number(scored, "score_delta_hybrid_minus_v1")
    add(scored.assign(_sort=delta).sort_values(["_sort", "field_key"]), "largest_negative", "Största sänkning mot Fast V1", 10)
    add(scored.assign(_sort=delta).sort_values(["_sort", "field_key"], ascending=[False, True]), "largest_positive", "Största höjning mot Fast V1", 10)
    holes = scored[_number(scored, "hole_count").gt(0)].sort_values(["absolute_delta", "field_key"], ascending=[False, True])
    add(holes, "holes", "Hålskifte med stor absolut förändring", 10)

    in_support = scored[scored["drift_score_source"].eq("FAST_V2_ROUTECAL")].copy()
    in_features = features.loc[in_support.index]
    inside_distances = pd.DataFrame(index=in_support.index)
    for name, (low, high) in ranges.items():
        span = float(high) - float(low)
        inside_distances[name] = np.minimum(
            (in_features[name] - float(low)).abs(),
            (float(high) - in_features[name]).abs(),
        ) / span
    in_support["_boundary_distance"] = inside_distances.min(axis=1)
    in_support["_boundary_feature"] = inside_distances.idxmin(axis=1)
    in_support = in_support.sort_values(["_boundary_distance", "field_key"])
    add(in_support, "inside_boundary", "Precis innanför en kalibreringsgräns", 10)

    fallback = scored[scored["drift_score_source"].str.startswith("FAST_V1_FALLBACK")].copy()
    fallback_features = features.loc[fallback.index]
    outside_distances = pd.DataFrame(0.0, index=fallback.index, columns=ranges)
    for name, (low, high) in ranges.items():
        span = float(high) - float(low)
        outside_distances[name] = np.maximum.reduce([
            ((float(low) - fallback_features[name]) / span).fillna(math.inf).to_numpy(),
            ((fallback_features[name] - float(high)) / span).fillna(math.inf).to_numpy(),
            np.zeros(len(fallback)),
        ])
    fallback["_boundary_distance"] = outside_distances.max(axis=1)
    fallback["_boundary_feature"] = outside_distances.idxmax(axis=1)
    fallback = fallback.replace([np.inf, -np.inf], np.nan).dropna(subset=["_boundary_distance"])
    fallback = fallback[fallback["_boundary_distance"].gt(0)].sort_values(["_boundary_distance", "field_key"])
    add(fallback, "outside_boundary", "Precis utanför kalibreringsstödet · officiellt Fast V1", 10)

    if len(selected) < min(MIN_REVIEW_ROWS, limit):
        add(
            scored.sort_values(["absolute_delta", "field_key"], ascending=[False, True]),
            "absolute_change_fill", "Stor absolut förändring · utfyllnad till robust stickprov",
            len(scored),
        )

    review = pd.DataFrame(selected.values()).head(limit).copy()
    if review.empty:
        return review
    review.insert(0, "review_order", range(1, len(review) + 1))
    review["review_status"] = ""
    review["review_note"] = ""
    review["local_url"] = review.apply(
        lambda row: "http://localhost:8000/?" + urlencode({
            "kommun": row["kommun"], "block": row["block_id"],
            "skifte": row["skifte_id"], "lager": "drift",
        }),
        axis=1,
    )
    columns = [
        "review_order", "qa_category", "qa_reason", "review_status", "review_note",
        "kommun", "block_id", "skifte_id", "local_url", "area_ha", "hole_count",
        "fast_v1_akerdrift_score", "akerdrift_score", "score_delta_hybrid_minus_v1",
        "rectangularity", "compactness", "erl", "drift_score_source",
    ]
    optional = ["_boundary_feature", "_boundary_distance"]
    return review[[column for column in columns + optional if column in review.columns]]


def write_html(review: pd.DataFrame, destination: Path) -> None:
    rows = []
    for _, row in review.iterrows():
        delta = float(row["score_delta_hybrid_minus_v1"])
        rows.append(
            "<tr>"
            f"<td>{int(row['review_order'])}</td>"
            f"<td>{html.escape(str(row['qa_category']))}</td>"
            f"<td>{html.escape(str(row['kommun']))}</td>"
            f"<td>{html.escape(str(row['block_id']))} · {html.escape(str(row['skifte_id']))}</td>"
            f"<td>{float(row['area_ha']):.2f}</td><td>{int(float(row['hole_count']))}</td>"
            f"<td>{float(row['fast_v1_akerdrift_score']):.1f} → {float(row['akerdrift_score']):.1f}</td>"
            f"<td class={'neg' if delta < 0 else 'pos'}>{delta:+.1f}</td>"
            f"<td><a href=\"{html.escape(str(row['local_url']), quote=True)}\" target=\"_blank\">Öppna skiftet</a></td>"
            "</tr>"
        )
    document = f"""<!doctype html><html lang="sv"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ÅkerDrift Hybrid RC1 · visuell QA</title>
<style>body{{font:15px system-ui;margin:24px;color:#172019}}h1{{margin-bottom:4px}}p{{max-width:900px;color:#59635b}}table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #d8ddd4;padding:8px;text-align:left}}th{{position:sticky;top:0;background:#fffef9}}a{{color:#294d32;font-weight:700}}.neg{{color:#a52020}}.pos{{color:#176b35}}</style>
<h1>ÅkerDrift Hybrid RC1 · visuell QA</h1><p>Starta först <code>START_AKERPASS_LOCAL.bat</code>. Kontrollera att färg, form, hål och poäng känns rimliga. Skriv OK/AVVIKELSE och kommentar i CSV-filen.</p>
<table><thead><tr><th>#</th><th>Kategori</th><th>Kommun</th><th>Block · skifte</th><th>ha</th><th>hål</th><th>V1 → Hybrid</th><th>Δ</th><th>Karta</th></tr></thead><tbody>{''.join(rows)}</tbody></table></html>"""
    destination.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--model-config", default=str(DEFAULT_MODEL))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    input_path, model_path, output_dir = Path(args.input), Path(args.model_config), Path(args.output_dir)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    frame = pd.read_parquet(input_path)
    config = json.loads(model_path.read_text(encoding="utf-8"))
    review = select_review_rows(frame, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "visual_review.csv"
    html_path = output_dir / "visual_review.html"
    review.to_csv(csv_path, index=False, encoding="utf-8-sig")
    write_html(review, html_path)
    print(f"VISUELL QA: {len(review)} skiften · {csv_path}")
    print(f"KLICKLISTA: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
