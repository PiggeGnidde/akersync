#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the public ÅkerVärde 2026 index for current skiften.

The frozen BASE model is read from its immutable coefficient artifact.  The
monetary prediction exists only as an in-memory intermediate and is never
written.  Output is an explicit allow-list of public index fields.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from common import MUN_CODES, load_config


MODEL_VERSION = "akervarde-v1.0-rc1"
REFERENCE_YEAR = 2026
REFERENCE_RATE = 600_000.0
P10_FACTOR = 0.8256
P90_FACTOR = 1.4886

REQUIRED_TERMS = (
    "arable_log_rate0",
    "arable_year_centered",
    "arable_log_area_20",
    "arable_lat_centered",
    "arable_lon_centered",
)

PUBLIC_COLUMNS = (
    "blockid",
    "skiftesbeteckning",
    "kommun",
    "akervarde",
    "akervarde_p10",
    "akervarde_p90",
    "akervarde_model_version",
    "akervarde_reference_year",
)


def read_frozen_coefficients(path: Path) -> dict[str, float]:
    if not path.exists():
        raise FileNotFoundError(
            f"Saknar fryst ÅkerVärde-artifact: {path}\n"
            "Kör FREEZE_AKERVARDE_V1RC.bat först. Modellen får inte skattas om i webbbygget."
        )
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if not {"term", "coefficient"}.issubset(frame.columns):
        raise RuntimeError(f"{path} saknar term/coefficient")
    if frame["term"].duplicated().any():
        dupes = frame.loc[frame["term"].duplicated(), "term"].astype(str).tolist()
        raise RuntimeError("Duplicerade frysta koefficienter: " + ", ".join(dupes))
    coefficients = dict(zip(frame["term"].astype(str), pd.to_numeric(frame["coefficient"], errors="raise")))
    missing = [term for term in REQUIRED_TERMS if term not in coefficients]
    if missing:
        raise RuntimeError("Fryst BASE-artifact saknar: " + ", ".join(missing))
    return {term: float(coefficients[term]) for term in REQUIRED_TERMS}


def municipality_by_block(blocks: gpd.GeoDataFrame) -> dict[str, str]:
    if "blockid" not in blocks or "region_kod" not in blocks:
        raise RuntimeError("Blockfilen måste innehålla blockid och region_kod")
    region = blocks["region_kod"].astype(str)
    blockids = blocks["blockid"].astype(str)
    result: dict[str, str] = {}
    for municipality, code in MUN_CODES.items():
        for blockid in blockids[region.str.startswith(code)]:
            result[str(blockid)] = municipality
    return result


def compute_public_index(features: pd.DataFrame, coefficients: dict[str, float]) -> pd.DataFrame:
    """Return only public index columns from prepared field features."""
    required = {"blockid", "skiftesbeteckning", "kommun", "area_ha", "lat", "lon"}
    missing = sorted(required - set(features.columns))
    if missing:
        raise RuntimeError("Skiftesfeatures saknar: " + ", ".join(missing))

    area = pd.to_numeric(features["area_ha"], errors="coerce").to_numpy(float)
    lat = pd.to_numeric(features["lat"], errors="coerce").to_numpy(float)
    lon = pd.to_numeric(features["lon"], errors="coerce").to_numpy(float)
    valid = np.isfinite(area) & (area > 0) & np.isfinite(lat) & np.isfinite(lon)
    if not valid.all():
        bad = int((~valid).sum())
        raise RuntimeError(f"{bad} skiften saknar positiv area eller giltig centroid")

    eta = np.full(len(features), coefficients["arable_log_rate0"], dtype=float)
    eta += coefficients["arable_year_centered"] * (REFERENCE_YEAR - 2024.0)
    eta += coefficients["arable_log_area_20"] * np.log(area / 20.0)
    eta += coefficients["arable_lat_centered"] * (lat - 55.5)
    eta += coefficients["arable_lon_centered"] * (lon - 13.0)

    # Deliberately ephemeral. Never add this intermediate to a DataFrame or file.
    frozen_base_rate = np.exp(np.clip(eta, -20.0, 25.0))
    index = 100.0 * frozen_base_rate / REFERENCE_RATE

    public = pd.DataFrame({
        "blockid": features["blockid"].astype(str),
        "skiftesbeteckning": features["skiftesbeteckning"].astype(str),
        "kommun": features["kommun"].astype(str),
        "akervarde": index,
        "akervarde_p10": P10_FACTOR * index,
        "akervarde_p90": P90_FACTOR * index,
        "akervarde_model_version": MODEL_VERSION,
        "akervarde_reference_year": REFERENCE_YEAR,
    })
    for column in ("akervarde", "akervarde_p10", "akervarde_p90"):
        public[column] = public[column].round(4)
    return public.loc[:, PUBLIC_COLUMNS]


def field_features(config: dict) -> pd.DataFrame:
    blocks_path = Path(config["blocks"])
    skiften_path = Path(config["skiften"])
    if not blocks_path.exists() or not skiften_path.exists():
        raise FileNotFoundError("Block- eller skiftefil saknas i config/local_paths.json")

    blocks = gpd.read_file(blocks_path)
    skiften = gpd.read_file(skiften_path)
    if skiften.crs is None:
        raise RuntimeError("Skiftefilen saknar CRS")
    skiften = skiften.to_crs(3006)
    skiften = skiften[skiften.geometry.notna() & ~skiften.geometry.is_empty].copy()
    skiften["blockid"] = skiften["blockid"].astype(str)
    skiften["skiftesbeteckning"] = skiften["skiftesbeteckning"].astype(str)

    block_to_municipality = municipality_by_block(blocks)
    centroids = gpd.GeoSeries(skiften.geometry.centroid, crs=3006).to_crs(4326)
    features = pd.DataFrame({
        "blockid": skiften["blockid"].to_numpy(),
        "skiftesbeteckning": skiften["skiftesbeteckning"].to_numpy(),
        "kommun": skiften["blockid"].map(block_to_municipality).to_numpy(),
        "area_ha": skiften.geometry.area.to_numpy(float) / 10_000.0,
        "lat": centroids.y.to_numpy(float),
        "lon": centroids.x.to_numpy(float),
    })
    if features["kommun"].isna().any():
        raise RuntimeError(f"{int(features['kommun'].isna().sum())} skiften kunde inte kopplas till kommun")
    return features


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/local_paths.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    build_dir = root / config.get("build_dir", "data/derived")
    freeze_dir = build_dir / "akervarde_v1_0_rc1_freeze"
    out_dir = build_dir / "akerpass_public_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    coefficients = read_frozen_coefficients(freeze_dir / "model_coefficients.csv")
    public = compute_public_index(field_features(config), coefficients)
    output = out_dir / "akervarde_public_skiften.csv"
    public.to_csv(output, index=False, encoding="utf-8-sig")

    metadata = {
        "model_version": MODEL_VERSION,
        "reference_year": REFERENCE_YEAR,
        "point": "frozen BASE prediction normalized to the public index",
        "prediction_interval_factors": {"p10": P10_FACTOR, "p90": P90_FACTOR},
        "fields": list(PUBLIC_COLUMNS),
        "contains_monetary_fields": False,
        "skiften": int(len(public)),
    }
    (out_dir / "akervarde_public_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    over_100 = int((public["akervarde"] > 100).sum())
    print(f"ÅkerVärde public index: OK · {len(public):,} skiften · {over_100:,} över 100")
    print("Output:", output)
    print("Monetära outputfält: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
