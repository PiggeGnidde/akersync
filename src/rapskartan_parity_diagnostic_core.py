"""Offline-only diagnostics. No changes to the production image engine or gates."""
from __future__ import annotations

import contextlib
import json
import re
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from rapskartan_map_product_core import (
    FORBIDDEN_PRODUCT_COLUMNS, _multihash_digest, local_asset_path, sha256_file,
)


def offline_audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
        raise RuntimeError(f"OFFLINE_ONLY: blocked network operation {event}")


def local_path(value: Path) -> Path:
    # WindowsPath changes /vsicurl/file into \\vsicurl\\file. Normalize only
    # the strings used for validation; retain the original filesystem path.
    text = str(value).replace("\\", "/")
    if text.lower().startswith(("//", "/vsi")) or re.match(r"^(https?|s3|ftp):", text, re.IGNORECASE):
        raise RuntimeError("OFFLINE_ONLY: only local filesystem paths are allowed")
    resolved = value.resolve()
    if str(resolved).replace("\\", "/").lower().startswith(("//", "/vsi")):
        raise RuntimeError("OFFLINE_ONLY: path resolves outside local storage")
    return resolved


def ensure_separate_output(output: Path, inputs: list[Path]) -> None:
    for source in inputs:
        if output == source or output in source.parents or source in output.parents:
            raise RuntimeError(f"Diagnostic output overlaps an input: {source}")


@contextlib.contextmanager
def heartbeat(label: str, seconds: float = 30):
    stop = threading.Event()
    started = time.monotonic()

    def report():
        while not stop.wait(seconds):
            print(f"[DIAG] {label} ... {time.monotonic()-started:.0f}s elapsed", flush=True)

    worker = threading.Thread(target=report, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=2)


class Tee:
    def __init__(self, screen, log):
        self.screen, self.log = screen, log

    def write(self, text):
        self.screen.write(text)
        self.log.write(text)
        self.log.flush()
        return len(text)

    def flush(self):
        self.screen.flush()
        self.log.flush()


def read_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={
        "development_field_id": str, "current_field_id": str,
        "municipality_code": str, "field_id": str,
    })
    if FORBIDDEN_PRODUCT_COLUMNS & set(frame.columns):
        raise RuntimeError(f"Ground-truth columns are forbidden in diagnostic inputs: {path.name}")
    return frame


def save_table(path: Path, frame: pd.DataFrame) -> None:
    # Preserve double precision; do not introduce the old 10-digit CSV round trip.
    frame.to_csv(path, index=False, float_format="%.17g")


def compare_tables(local: pd.DataFrame, reference: pd.DataFrame, keys: list[str],
                   columns: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    joined = local[keys + columns].merge(
        reference[keys + columns], on=keys, how="outer", validate="one_to_one",
        suffixes=("_local", "_reference"), indicator=True,
    )
    summaries = []
    deltas = {}
    for column in columns:
        a = pd.to_numeric(joined[f"{column}_local"], errors="raise")
        b = pd.to_numeric(joined[f"{column}_reference"], errors="raise")
        both = np.isfinite(a) & np.isfinite(b)
        delta = a - b
        absolute = delta[both].abs()
        deltas[f"{column}_delta"] = delta
        summaries.append({
            "variable": column, "matched_rows": int(joined["_merge"].eq("both").sum()),
            "unmatched_rows": int(joined["_merge"].ne("both").sum()),
            "finite_pairs": int(both.sum()),
            "missing_mismatch": int(a.isna().ne(b.isna()).sum()),
            "nonfinite_nonmissing_pairs": int(((~both) & (~a.isna()) & (~b.isna())).sum()),
            "mean_signed_delta": float(delta[both].mean()) if both.any() else None,
            "median_abs_delta": float(absolute.median()) if both.any() else None,
            "p95_abs_delta": float(absolute.quantile(.95)) if both.any() else None,
            "max_abs_delta": float(absolute.max()) if both.any() else None,
        })
    joined = pd.concat([joined, pd.DataFrame(deltas, index=joined.index)], axis=1)
    return joined, pd.DataFrame(summaries)


def validate_scenes(document: dict, contract: dict) -> list[dict]:
    scenes = document.get("items", [])
    if not scenes or len(scenes) > contract["resource_guards"]["maximum_scene_items"]:
        raise RuntimeError("Invalid/beyond-contract scene inventory")
    expected = set(contract["scene_archive"]["reflectance_assets"]) | {"SCL"}
    ids = set()
    for scene in scenes:
        identity = scene["item_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identity) or identity in ids:
            raise RuntimeError("Invalid/duplicate scene identity")
        ids.add(identity)
        if set(scene["assets"]) != expected:
            raise RuntimeError("Scene bands differ from the frozen contract")
        when = scene["datetime"]
        parse_time = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not parse_time(contract["scene_archive"]["time_from"]) <= parse_time(when) < parse_time(contract["scene_archive"]["time_to"]):
            raise RuntimeError("Scene acquisition is outside the frozen period")
        if scene["acquisition_date"] != when[:10]:
            raise RuntimeError("Scene date/timestamp mismatch")
        for asset in scene["assets"].values():
            parsed = urllib.parse.urlparse(asset["s3_uri"])
            if parsed.scheme != "s3" or parsed.netloc != contract["scene_archive"]["s3_bucket"]:
                raise RuntimeError("Unexpected source asset identity")
            if not asset.get("checksum") or int(asset.get("bytes", 0)) <= 0:
                raise RuntimeError("Diagnostic requires file size and checksum for every asset")
    return scenes


def verify_day_assets(scenes: list[dict], archive: Path) -> list[dict]:
    rows = []
    for scene in scenes:
        for band, asset in sorted(scene["assets"].items()):
            path = local_path(local_asset_path(archive, scene, band))
            if archive not in path.parents:
                raise RuntimeError("Scene asset resolves outside the local archive")
            if not path.is_file() or path.stat().st_size != int(asset["bytes"]):
                raise RuntimeError(f"OFFLINE_ONLY: missing/size-mismatched asset; no download attempted: {path}")
            if not _multihash_digest(path, asset["checksum"]):
                raise RuntimeError(f"Scene asset checksum mismatch (left untouched): {path}")
            rows.append({"item_id": scene["item_id"], "band": band,
                         "bytes": path.stat().st_size, "checksum": asset["checksum"],
                         "verified": True})
    return rows


def read_day_checkpoint(folder: Path, day: str, identity: str) -> pd.DataFrame | None:
    data, meta = folder / f"{day}.parquet", folder / f"{day}.json"
    if not data.exists() and not meta.exists():
        return None
    if not meta.exists():
        # Interrupted atomic save: data is reproducible, but never trust it yet.
        return None
    record = json.loads(meta.read_text(encoding="utf-8"))
    if record.get("identity") != identity or not data.is_file() or record.get("sha256") != sha256_file(data):
        raise RuntimeError(f"Diagnostic checkpoint mismatch; preserved for inspection: {data}")
    frame = pd.read_parquet(data)
    if len(frame) != record["rows"] or (not frame.empty and set(frame.acquisition_date) != {day}):
        raise RuntimeError(f"Diagnostic checkpoint row/date mismatch: {data}")
    return frame


def save_day_checkpoint(folder: Path, day: str, identity: str, frame: pd.DataFrame) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    meta = folder / f"{day}.json"
    temporary_meta = meta.with_suffix(".json.tmp")
    temporary_meta.write_text(json.dumps({"identity": identity, "rows": len(frame),
                                         "sha256": sha256_file(path)}, indent=2), encoding="utf-8")
    temporary_meta.replace(meta)
