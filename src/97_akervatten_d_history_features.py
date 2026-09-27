#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT D · historical raw-feature engineering.

D intentionally does NOT create/freeze a composite ÅkerVatten score.

Groundwater:
  C-frozen field -> SGU-HYPE omrade_id
  -> official daily history
  -> persistence/seasonality features for grundvattensituation/fyllnadsgrad.

Surface water:
  C-frozen field -> SVAR ARO_UUID -> Vattenwebb Aroid -> Subid
  -> official S-HYPE historical flow-statistics workbook
  -> MQ/MLQ and derived low-flow raw features.

All source downloads and field joins are resumable.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_d.json"
KEY = ["blockid", "skiftesbeteckning"]

_spec = importlib.util.spec_from_file_location(
    "akervatten_b", ROOT / "src" / "94_akervatten_b_pilot.py"
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Could not load STOPPUNKT B helpers")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt_duration(seconds: float | None) -> str:
    if seconds is None or not np.isfinite(seconds) or seconds < 0:
        return "--:--:--"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def norm_id(v: Any) -> str | None:
    if pd.isna(v):
        return None
    return re.sub(r"\.0$", "", str(v).strip()).upper()


def norm_id_series(s: pd.Series) -> pd.Series:
    return s.map(norm_id).astype("string")


def chunk_ranges(n: int, size: int) -> list[tuple[int, int, int]]:
    if n <= 0 or size <= 0:
        raise ValueError((n, size))
    return [
        (i + 1, start, min(n, start + size))
        for i, start in enumerate(range(0, n, size))
    ]


def add_query(url: str, **updates: Any) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    for k, v in updates.items():
        q[str(k)] = str(v)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def read_sgu_csv(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    last = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        for sep in (",", ";", "\t"):
            try:
                df = pd.read_csv(
                    pd.io.common.StringIO(text),
                    sep=sep,
                    dtype=str,
                    low_memory=False,
                )
            except Exception as exc:
                last = exc
                continue
            df.columns = [str(c).strip().lower() for c in df.columns]
            required = {
                "datum", "omrade_id",
                "grundvattensituation_sma", "grundvattensituation_stora",
                "fyllnadsgrad_sma", "fyllnadsgrad_stora",
            }
            if required.issubset(df.columns):
                return df
    raise RuntimeError(f"Could not parse SGU-HYPE CSV {path}: {last}")


def validate_sgu_history(df: pd.DataFrame, expected_id: str, min_years: int) -> dict[str, Any]:
    q = df.copy()
    q["datum"] = pd.to_datetime(q["datum"], errors="coerce")
    q = q[q["datum"].notna()].copy()
    ids = sorted(set(q["omrade_id"].dropna().astype(str).str.replace(r"\.0$", "", regex=True)))
    if ids != [str(expected_id)]:
        raise RuntimeError(f"SGU history ID mismatch for {expected_id}: ids={ids[:10]}")
    if q.empty:
        raise RuntimeError(f"SGU history {expected_id} has no valid dates")

    start = q["datum"].min()
    end = q["datum"].max()
    years = (end - start).days / 365.2425
    if years < min_years:
        raise RuntimeError(
            f"SGU history {expected_id} spans only {years:.1f} years "
            f"({start.date()}..{end.date()}); expected >= {min_years}. "
            "Response may be truncated."
        )
    return {
        "rows": int(len(q)),
        "date_start": str(start.date()),
        "date_end": str(end.date()),
        "history_years": float(years),
    }


def download_one_sgu_history(
    dl: Any,
    omrade_id: str,
    url: str,
    target: Path,
    b_cache_dir: Path,
    max_bytes: int,
    min_years: int,
) -> tuple[str, dict[str, Any], bool]:
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size > 0:
        df = read_sgu_csv(target)
        info = validate_sgu_history(df, omrade_id, min_years)
        return "cache", info, False

    for old in sorted(b_cache_dir.glob(f"sgu_hype_{omrade_id}.*")):
        try:
            df = read_sgu_csv(old)
            info = validate_sgu_history(df, omrade_id, min_years)
            shutil.copy2(old, target)
            return "B-cache", info, True
        except Exception:
            pass

    # Ask explicitly for a large result. The post-download history-span validation
    # catches any server-side cap/truncation before the full run can continue.
    full_url = add_query(url, limit=100000)
    r = dl.get(full_url, stream=True, timeout=300)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.unlink(missing_ok=True)
    total = 0
    with tmp.open("wb") as fh:
        for chunk in r.iter_content(1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"SGU history {omrade_id} exceeded per-file limit "
                    f"{max_bytes/1024/1024:.1f} MB"
                )
            fh.write(chunk)

    df = read_sgu_csv(tmp)
    info = validate_sgu_history(df, omrade_id, min_years)
    os.replace(tmp, target)
    return "download", info, True


def consecutive_true_run(dates: pd.Series, mask: pd.Series) -> int:
    if len(dates) == 0:
        return 0
    q = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "hit": mask.fillna(False).astype(bool).to_numpy(),
    }).dropna(subset=["date"]).sort_values("date")
    best = 0
    run = 0
    prev = None
    for row in q.itertuples(index=False):
        continuous = prev is not None and (row.date - prev).days == 1
        if row.hit:
            run = run + 1 if continuous else 1
            best = max(best, run)
        else:
            run = 0
        prev = row.date
    return int(best)


def annual_run_stats(dates: pd.Series, values: pd.Series, threshold: float) -> tuple[float | None, float | None]:
    q = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "v": pd.to_numeric(values, errors="coerce"),
    }).dropna(subset=["date", "v"])
    if q.empty:
        return None, None
    runs = []
    for _, y in q.groupby(q["date"].dt.year):
        runs.append(consecutive_true_run(y["date"], y["v"] <= threshold))
    if not runs:
        return None, None
    return float(np.median(runs)), float(np.quantile(runs, 0.90))


def annual_min_stats(dates: pd.Series, values: pd.Series, months: set[int] | None = None) -> tuple[float | None, float | None]:
    q = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "v": pd.to_numeric(values, errors="coerce"),
    }).dropna(subset=["date", "v"])
    if months is not None:
        q = q[q["date"].dt.month.isin(months)]
    if q.empty:
        return None, None
    mins = q.groupby(q["date"].dt.year)["v"].min()
    if mins.empty:
        return None, None
    return float(mins.median()), float(mins.quantile(0.10))


def add_series_features(
    out: dict[str, Any],
    prefix: str,
    dates: pd.Series,
    values: pd.Series,
    irrigation_months: set[int],
    thresholds: list[int],
) -> None:
    v = pd.to_numeric(values, errors="coerce")
    v = v.where((v >= 0) & (v <= 100))
    d = pd.to_datetime(dates, errors="coerce")
    valid = d.notna() & v.notna()
    d = d[valid].reset_index(drop=True)
    v = v[valid].reset_index(drop=True)

    out[f"{prefix}_n_valid"] = int(len(v))
    if v.empty:
        for suffix in (
            "median","p10","summer_median","summer_p10",
            "annual_min_median","annual_min_p10",
            "summer_annual_min_median","summer_annual_min_p10"
        ):
            out[f"{prefix}_{suffix}"] = None
        for th in thresholds:
            out[f"{prefix}_le{th}_fraction"] = None
            out[f"{prefix}_summer_le{th}_fraction"] = None
            out[f"{prefix}_le{th}_max_run_days"] = None
            out[f"{prefix}_le{th}_annual_max_run_median"] = None
            out[f"{prefix}_le{th}_annual_max_run_p90"] = None
        return

    summer = d.dt.month.isin(irrigation_months)
    out[f"{prefix}_median"] = float(v.median())
    out[f"{prefix}_p10"] = float(v.quantile(0.10))
    out[f"{prefix}_summer_median"] = float(v[summer].median()) if summer.any() else None
    out[f"{prefix}_summer_p10"] = float(v[summer].quantile(0.10)) if summer.any() else None

    amin_med, amin_p10 = annual_min_stats(d, v)
    samin_med, samin_p10 = annual_min_stats(d, v, irrigation_months)
    out[f"{prefix}_annual_min_median"] = amin_med
    out[f"{prefix}_annual_min_p10"] = amin_p10
    out[f"{prefix}_summer_annual_min_median"] = samin_med
    out[f"{prefix}_summer_annual_min_p10"] = samin_p10

    for th in thresholds:
        hit = v <= th
        out[f"{prefix}_le{th}_fraction"] = float(hit.mean())
        out[f"{prefix}_summer_le{th}_fraction"] = float(hit[summer].mean()) if summer.any() else None
        out[f"{prefix}_le{th}_max_run_days"] = consecutive_true_run(d, hit)
        rmed, rp90 = annual_run_stats(d, v, float(th))
        out[f"{prefix}_le{th}_annual_max_run_median"] = rmed
        out[f"{prefix}_le{th}_annual_max_run_p90"] = rp90


def sgu_features(path: Path, expected_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    df = read_sgu_csv(path)
    info = validate_sgu_history(
        df, expected_id, int(cfg["sgu_hype"]["min_history_years_small"])
    )
    d = pd.to_datetime(df["datum"], errors="coerce")
    out: dict[str, Any] = {
        "omrade_id": str(expected_id),
        "gw_history_rows": info["rows"],
        "gw_history_start": info["date_start"],
        "gw_history_end": info["date_end"],
        "gw_history_years": info["history_years"],
        "gw_source_sha256": sha256(path),
    }

    months = set(int(x) for x in cfg["sgu_hype"]["irrigation_months"])
    thresholds = [int(x) for x in cfg["sgu_hype"]["low_thresholds"]]

    for size, sw in (("sma", "small"), ("stora", "large")):
        add_series_features(
            out, f"gw_{sw}_situation", d,
            df[f"grundvattensituation_{size}"], months, thresholds
        )
        add_series_features(
            out, f"gw_{sw}_fill", d,
            df[f"fyllnadsgrad_{size}"], months, thresholds
        )
    return out


def find_flowstats_headers(raw: pd.DataFrame) -> tuple[int, int, list[str | None]]:
    header_row = None
    for r in range(min(100, len(raw))):
        vals = [str(v).strip().upper() for v in raw.iloc[r].tolist() if pd.notna(v)]
        if "SUBID" in vals and "AROID" in vals:
            header_row = r
            break
    if header_row is None:
        raise RuntimeError("Could not locate Subid/Aroid header row in flow-statistics sheet")

    known = ("HQ50", "HQ10", "HQ2", "MHQ", "MQ", "MLQ")
    best = None
    for r in range(header_row):
        row = raw.iloc[r].tolist()
        hits = 0
        for v in row:
            if pd.isna(v):
                continue
            txt = str(v).strip().upper()
            if any(re.search(rf"(?<![A-Z0-9]){re.escape(k)}(?![A-Z0-9])", txt) for k in known):
                hits += 1
        if best is None or hits > best[0]:
            best = (hits, r)
    if best is None or best[0] < 2:
        preview = raw.iloc[:header_row + 1, :20].fillna("").astype(str).to_dict(orient="split")
        raise RuntimeError(f"Could not locate statistical-label row; preview={preview}")

    stat_row = best[1]
    labels: list[str | None] = []
    current = None
    for v in raw.iloc[stat_row].tolist():
        txt = "" if pd.isna(v) else str(v).strip().upper()
        found = None
        for k in known:
            if re.search(rf"(?<![A-Z0-9]){re.escape(k)}(?![A-Z0-9])", txt):
                found = k
                break
        if found:
            current = found
        labels.append(current)
    return header_row, stat_row, labels


def flow_kind(header: str) -> str | None:
    s = header.lower()
    if "stationskorrigerad" in s:
        return "stationscorr"
    if "naturlig" in s:
        return "natural"
    if "total" in s and "vattenf" in s:
        return "total"
    return None


def read_flowstats_features(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    sheets = pd.read_excel(path, sheet_name=None, header=None, engine="xlrd", dtype=object)
    name = next((n for n in sheets if "flödesstatistik" in n.lower() or "flodesstatistik" in n.lower()), None)
    if name is None:
        raise RuntimeError(f"No Flödesstatistik sheet; sheets={list(sheets)}")
    raw = sheets[name]
    header_row, stat_row, stat_labels = find_flowstats_headers(raw)
    hdr = raw.iloc[header_row].tolist()

    subid_idx = next(i for i,v in enumerate(hdr) if str(v).strip().upper() == "SUBID")
    aroid_idx = next(i for i,v in enumerate(hdr) if str(v).strip().upper() == "AROID")
    area_idx = next(
        (i for i,v in enumerate(hdr) if "AREA" in str(v).upper() and "KM" in str(v).upper()),
        None
    )

    table = pd.DataFrame({
        "Subid_flowstats": raw.iloc[header_row+1:, subid_idx].to_numpy(),
        "Aroid_flowstats": raw.iloc[header_row+1:, aroid_idx].to_numpy(),
    })
    if area_idx is not None:
        table["flowstats_area_km2"] = pd.to_numeric(
            raw.iloc[header_row+1:, area_idx], errors="coerce"
        ).to_numpy()

    recognized = []
    for col_idx in range(len(hdr)):
        stat = stat_labels[col_idx] if col_idx < len(stat_labels) else None
        kind = flow_kind(str(hdr[col_idx]))
        if stat is None or kind is None:
            continue
        cname = f"sw_{stat}_{kind}_m3s"
        table[cname] = pd.to_numeric(
            raw.iloc[header_row+1:, col_idx], errors="coerce"
        ).to_numpy()
        recognized.append({
            "column_index": col_idx,
            "statistic": stat,
            "flow_kind": kind,
            "raw_header": str(hdr[col_idx]),
            "canonical": cname,
        })

    table = table[table["Subid_flowstats"].notna() & table["Aroid_flowstats"].notna()].copy()
    table["_subid"] = norm_id_series(table["Subid_flowstats"])
    table["_aroid"] = norm_id_series(table["Aroid_flowstats"])
    table = table.drop_duplicates("_aroid")

    required = [
        "sw_MQ_total_m3s", "sw_MLQ_total_m3s",
        "sw_MQ_natural_m3s", "sw_MLQ_natural_m3s",
    ]
    missing = [c for c in required if c not in table.columns]
    if missing:
        raise RuntimeError(
            f"Flow-statistics parser missing required columns {missing}; "
            f"recognized={recognized}"
        )

    for kind in ("total", "stationscorr", "natural"):
        mq = f"sw_MQ_{kind}_m3s"
        mlq = f"sw_MLQ_{kind}_m3s"
        if mq in table.columns and mlq in table.columns:
            table[f"sw_MLQ_MQ_ratio_{kind}"] = (
                table[mlq] / table[mq].where(table[mq] > 0)
            )

    info = {
        "sheet": name,
        "header_row_zero_based": int(header_row),
        "statistic_row_zero_based": int(stat_row),
        "recognized_columns": recognized,
        "rows": int(len(table)),
    }
    return table, info


def prepare_surface_units(c_links: pd.DataFrame, flow: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    need = ["ARO_UUID", "Subid"]
    missing = [c for c in need if c not in c_links.columns]
    if missing:
        raise RuntimeError(f"C links missing {missing}")

    cols = ["ARO_UUID", "Subid"]
    for c in ("Vattenwebb_Aroid", "AREA", "AREA_UPSTREAM"):
        if c in c_links.columns:
            cols.append(c)

    units = c_links[cols].drop_duplicates().copy()
    by_sub = units.groupby(units["Subid"].map(norm_id), dropna=True)["ARO_UUID"].nunique()
    if (by_sub > 1).any():
        raise RuntimeError("A Subid maps to multiple ARO_UUID values in C-frozen links")

    units = units.drop_duplicates(subset=["Subid"]).copy()
    units["_subid_c"] = norm_id_series(units["Subid"])
    units["_aroid_c"] = norm_id_series(
        units["Vattenwebb_Aroid"] if "Vattenwebb_Aroid" in units.columns else units["ARO_UUID"]
    )

    out = units.merge(
        flow,
        left_on="_aroid_c", right_on="_aroid",
        how="left", validate="one_to_one",
    )
    same_subid = (
        out["_subid"].isna()
        | out["_subid_c"].isna()
        | out["_subid"].eq(out["_subid_c"])
    )
    if not same_subid.all():
        bad = out.loc[~same_subid, ["ARO_UUID","Subid","Subid_flowstats"]].head(10)
        raise RuntimeError(f"C Subid disagrees with flowstats after Aroid mapping: {bad.to_dict('records')}")

    if "AREA_UPSTREAM" in out.columns:
        area = pd.to_numeric(out["AREA_UPSTREAM"], errors="coerce")
        for stat in ("MQ", "MLQ"):
            for kind in ("total", "stationscorr", "natural"):
                c = f"sw_{stat}_{kind}_m3s"
                if c in out.columns:
                    out[f"sw_{stat}_{kind}_lps_km2_upstream"] = (
                        1000.0 * out[c] / area.where(area > 0)
                    )

    if "sw_MLQ_total_m3s" in out.columns and "sw_MLQ_natural_m3s" in out.columns:
        out["sw_MLQ_total_to_natural_ratio"] = (
            out["sw_MLQ_total_m3s"]
            / out["sw_MLQ_natural_m3s"].where(out["sw_MLQ_natural_m3s"] > 0)
        )

    info = {
        "unique_units": int(len(units)),
        "mapped_units": int(out["Aroid_flowstats"].notna().sum()),
    }
    return out, info


def write_nadia_batches(subids: list[str], cfg: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    size = int(cfg["nadia_d2_prep"]["batch_size_subids"])
    batches = []
    for i, start in enumerate(range(0, len(subids), size), start=1):
        ids = subids[start:start+size]
        path = out_dir / f"batch_{i:03d}_subids.txt"
        path.write_text(",".join(ids) + "\n", encoding="utf-8")
        batches.append({"batch": i, "count": len(ids), "file": str(path), "ids": ids})

    readme = out_dir / "README.txt"
    readme.write_text(
        "SMHI NADIA manual D2 preparation\n"
        "URL: https://vattenwebb.smhi.se/nadia/\n"
        f"Tidssteg: {cfg['nadia_d2_prep']['timestep']}\n"
        f"Från år: {cfg['nadia_d2_prep']['first_year']}\n"
        f"Till och med år: {cfg['nadia_d2_prep']['last_year']}\n"
        "Paste one batch file at a time into Delavrinningsområden (subid eller aroid).\n"
        "These batches are prepared for a later optional D2 daily-series augmentation;\n"
        "they are not required for the D1 historical baseline.\n",
        encoding="utf-8",
    )
    return {"batch_size": size, "n_batches": len(batches), "batches": batches, "readme": str(readme)}


def field_checkpoint_valid(path: Path, expected: pd.DataFrame) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        q = pd.read_parquet(path, columns=KEY)
    except Exception:
        return False
    return (
        len(q) == len(expected)
        and q[KEY].astype(str).reset_index(drop=True).equals(
            expected[KEY].astype(str).reset_index(drop=True)
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    cfg = read_json(Path(args.config))
    bcfg = read_json(ROOT / cfg["paths"]["b_config"])
    work = ROOT / cfg["output"]["work_dir"]
    raw = ROOT / cfg["output"]["raw_dir"]
    work.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)

    dl = B.Downloader(
        timeout=int(cfg["network"]["timeout_seconds"]),
        retries=int(cfg["network"]["retries"]),
        backoff=float(cfg["network"]["retry_backoff_seconds"]),
    )

    print("=" * 122)
    print("ÅkerVatten MVP v0a · STOPPUNKT D · HISTORICAL RAW FEATURES")
    print("=" * 122)
    print("No composite water-risk score is computed or frozen in D.")

    print("\n[1/7] C-frozen linkage inventory")
    c_path = ROOT / cfg["paths"]["c_links"]
    c = pd.read_parquet(c_path)
    if len(c) != 128636:
        raise RuntimeError(f"C population changed: {len(c):,}")
    if c[KEY].duplicated().any():
        raise RuntimeError("C links contain duplicate field keys")

    if "omrade_id" not in c.columns or "url_tidsserie" not in c.columns or "Subid" not in c.columns:
        raise RuntimeError("C links lack omrade_id/url_tidsserie/Subid")

    g_units = (
        c[["omrade_id","url_tidsserie"]]
        .dropna()
        .drop_duplicates()
        .copy()
    )
    url_counts = g_units.groupby(g_units["omrade_id"].astype(str))["url_tidsserie"].nunique()
    if (url_counts > 1).any():
        raise RuntimeError("One SGU-HYPE omrade_id has multiple history URLs")
    g_units = g_units.drop_duplicates("omrade_id")
    g_units["omrade_id"] = g_units["omrade_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    g_units = g_units.sort_values(
        "omrade_id", key=lambda s: pd.to_numeric(s, errors="coerce")
    ).reset_index(drop=True)

    subids = sorted(
        set(norm_id_series(c["Subid"]).dropna().tolist()),
        key=lambda x: int(x) if str(x).isdigit() else str(x),
    )
    print(f"  fields              : {len(c):,}")
    print(f"  unique SGU-HYPE ids : {len(g_units):,}")
    print(f"  unique S-HYPE Subid : {len(subids):,}")

    print("\n[2/7] SGU-HYPE daily-history acquisition · resumable per area")
    hist_dir = raw / "sgu_hype_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    b_hist = ROOT / cfg["paths"]["b_sgu_history_cache"]
    max_bytes = int(float(cfg["sgu_hype"]["max_file_mb"]) * 1024 * 1024)
    min_years = int(cfg["sgu_hype"]["min_history_years_small"])

    # Probe three areas first so a server-side row cap cannot waste a long run.
    probe_rows = g_units.head(min(3, len(g_units)))
    for r in probe_rows.itertuples(index=False):
        oid = str(r.omrade_id)
        path = hist_dir / f"sgu_hype_{oid}.csv"
        mode, info, _ = download_one_sgu_history(
            dl, oid, str(r.url_tidsserie), path, b_hist,
            max_bytes, min_years,
        )
        print(
            f"  probe {oid}: {mode} · {info['rows']:,} rows · "
            f"{info['date_start']}..{info['date_end']} · {info['history_years']:.1f} y"
        )

    start_time = time.monotonic()
    downloaded_this_run = 0
    completed = 0
    progress_every = int(cfg["sgu_hype"]["progress_every_areas"])
    source_state = work / "d_sgu_download_state.json"

    for r in g_units.itertuples(index=False):
        oid = str(r.omrade_id)
        path = hist_dir / f"sgu_hype_{oid}.csv"
        mode, info, wrote = download_one_sgu_history(
            dl, oid, str(r.url_tidsserie), path, b_hist,
            max_bytes, min_years,
        )
        completed += 1
        if wrote:
            downloaded_this_run += 1

        atomic_json(source_state, {
            "phase":"SGU_HISTORY_DOWNLOAD",
            "completed":completed,
            "total":len(g_units),
            "last_omrade_id":oid,
            "updated_utc":datetime.now(timezone.utc).isoformat(),
        })

        if completed % progress_every == 0 or completed == len(g_units):
            elapsed = time.monotonic() - start_time
            rate = completed / elapsed if elapsed > 0 else float("nan")
            eta = (len(g_units) - completed) / rate if rate > 0 else None
            print(
                f"  [SGU] {completed:4d}/{len(g_units):4d} · "
                f"{100*completed/len(g_units):5.1f}% · {rate:5.1f} areas/s · "
                f"ETA {fmt_duration(eta)} · last={oid} ({mode}) · checkpoint saved"
            )

    print("\n[3/7] SGU-HYPE historical feature extraction · resumable")
    feat_ckpt = work / "sgu_feature_checkpoints"
    feat_ckpt.mkdir(parents=True, exist_ok=True)
    feat_parts = []
    area_chunk = progress_every
    for chunk_no, start, end in chunk_ranges(len(g_units), area_chunk):
        ids = g_units.iloc[start:end]["omrade_id"].astype(str).tolist()
        p = feat_ckpt / f"sgu_features_{start+1:04d}_{end:04d}.parquet"
        valid = False
        if p.exists() and p.stat().st_size > 0:
            try:
                q = pd.read_parquet(p)
                valid = (
                    len(q) == len(ids)
                    and q["omrade_id"].astype(str).tolist() == ids
                )
            except Exception:
                valid = False
        if valid:
            feat_parts.append(pd.read_parquet(p))
            print(f"  [SGU FEATURES] {end:4d}/{len(g_units):4d} · RESUME checkpoint")
            continue

        rows = []
        for oid in ids:
            rows.append(sgu_features(hist_dir / f"sgu_hype_{oid}.csv", oid, cfg))
        q = pd.DataFrame(rows)
        atomic_parquet(q, p)
        feat_parts.append(q)
        print(f"  [SGU FEATURES] {end:4d}/{len(g_units):4d} · checkpoint saved")

    gw = pd.concat(feat_parts, ignore_index=True)
    atomic_parquet(gw, work / "groundwater_history_features.parquet")
    print(f"  groundwater feature rows: {len(gw):,}")

    print("\n[4/7] S-HYPE historical flow statistics (1981-2010 baseline)")
    flow_path = ROOT / cfg["paths"]["b_flowstats_cache"]
    if not flow_path.exists():
        flow_path = B.download_vattenwebb_excel(
            dl,
            bcfg["sources"]["smhi_vattenwebb_flowstatistics"],
            raw / "smhi" / "vattenwebb_flowstatistics.xls",
        )
    flow, flow_info = read_flowstats_features(flow_path)
    surface, surface_info = prepare_surface_units(c, flow)
    atomic_parquet(surface, work / "surfacewater_history_features.parquet")
    print(f"  flowstats rows       : {len(flow):,}")
    print(f"  Skåne S-HYPE units   : {surface_info['unique_units']:,}")
    print(f"  mapped flowstats     : {surface_info['mapped_units']:,}/{surface_info['unique_units']:,}")
    print("  recognized historical flow columns:")
    for x in flow_info["recognized_columns"]:
        if x["statistic"] in {"MQ","MLQ"}:
            print(f"    {x['canonical']}")

    print("\n[5/7] Prepare optional NADIA D2 daily-history batches")
    nadia = write_nadia_batches(subids, cfg, work / "nadia_d2_batches")
    print(
        f"  {len(subids):,} Subid -> {nadia['n_batches']} batches "
        f"of <= {nadia['batch_size']} IDs"
    )
    print("  batch directory:", work / "nadia_d2_batches")

    print("\n[6/7] Join historical unit features back to 128,636 fields · resumable")
    join_dir = work / "field_checkpoints"
    join_dir.mkdir(parents=True, exist_ok=True)
    ranges = chunk_ranges(len(c), int(cfg["field_join"]["chunk_size"]))
    gw2 = gw.copy()
    gw2["_oid"] = norm_id_series(gw2["omrade_id"])
    surf2 = surface.copy()
    surf2["_subid_join"] = norm_id_series(surf2["Subid"])

    run_start = time.monotonic()
    new_fields = 0
    parts = []
    for chunk_no, start, end in ranges:
        p = join_dir / f"fields_{start+1:06d}_{end:06d}.parquet"
        expected = c.iloc[start:end][KEY]
        if field_checkpoint_valid(p, expected):
            q = pd.read_parquet(p)
            parts.append(q)
            print(
                f"  [FIELDS] {end:6d}/{len(c):6d} · "
                f"{100*end/len(c):5.1f}% · RESUME checkpoint"
            )
            continue

        q = c.iloc[start:end].copy().reset_index(drop=True)
        q["_oid"] = norm_id_series(q["omrade_id"])
        q["_subid_join"] = norm_id_series(q["Subid"])
        q = q.merge(
            gw2.drop(columns=["omrade_id"]),
            on="_oid", how="left", validate="many_to_one",
            suffixes=("","_gw"),
        )
        q = q.merge(
            surf2.drop(columns=["Subid","ARO_UUID"], errors="ignore"),
            on="_subid_join", how="left", validate="many_to_one",
            suffixes=("","_sw"),
        )
        q = q.drop(columns=["_oid","_subid_join"], errors="ignore")
        atomic_parquet(q, p)
        if not field_checkpoint_valid(p, expected):
            raise RuntimeError(f"Field checkpoint validation failed: {p}")
        parts.append(q)

        new_fields += len(q)
        elapsed = time.monotonic() - run_start
        rate = new_fields / elapsed if elapsed > 0 else float("nan")
        eta = (len(c) - end) / rate if rate > 0 else None
        print(
            f"  [FIELDS] {end:6d}/{len(c):6d} · {100*end/len(c):5.1f}% · "
            f"{rate:8.1f} fields/s · ETA {fmt_duration(eta)} · checkpoint saved"
        )

    final = pd.concat(parts, ignore_index=True)
    if len(final) != len(c) or final[KEY].duplicated().any():
        raise RuntimeError("Final D field table failed population/identity QA")
    final_path = work / "akervatten_d_history_features_skane.parquet"
    atomic_parquet(final, final_path)

    print("\n[7/7] QA")
    small_years = pd.to_numeric(gw["gw_history_years"], errors="coerce")
    sgu_parse = int(gw["gw_small_situation_n_valid"].gt(0).sum())
    sgu_long = int(small_years.ge(min_years).sum())
    surf_mapped = int(surface["sw_MLQ_total_m3s"].notna().sum())

    field_gw = int(final["gw_small_situation_n_valid"].gt(0).sum())
    field_sw = int(final["sw_MLQ_total_m3s"].notna().sum())

    qa = {
        "sgu_units_total": int(len(g_units)),
        "sgu_units_parsed": sgu_parse,
        "sgu_units_long_history": sgu_long,
        "surface_units_total": int(len(surface)),
        "surface_units_with_MLQ": surf_mapped,
        "fields_total": int(len(final)),
        "fields_with_groundwater_history": field_gw,
        "fields_with_surface_MLQ": field_sw,
    }
    qa.update({
        "sgu_parse_pct": 100*sgu_parse/len(g_units),
        "sgu_long_history_pct": 100*sgu_long/len(g_units),
        "surface_mapping_pct": 100*surf_mapped/len(surface),
        "field_groundwater_pct": 100*field_gw/len(final),
        "field_surface_pct": 100*field_sw/len(final),
    })

    acc = cfg["acceptance"]
    problems = []
    checks = [
        ("sgu unit parse", qa["sgu_parse_pct"]/100, float(acc["min_sgu_unit_parse_fraction"])),
        ("sgu long history", qa["sgu_long_history_pct"]/100, float(acc["min_sgu_small_long_history_fraction"])),
        ("surface unit mapping", qa["surface_mapping_pct"]/100, float(acc["min_surface_unit_mapping_fraction"])),
        ("field groundwater", qa["field_groundwater_pct"]/100, float(acc["min_field_groundwater_feature_fraction"])),
        ("field surface", qa["field_surface_pct"]/100, float(acc["min_field_surface_feature_fraction"])),
    ]
    for name, actual, minimum in checks:
        if actual < minimum:
            problems.append(f"{name}: {actual:.3%} < {minimum:.3%}")

    summary = {
        "schema_version":"akervatten-mvp-v0a-d-history-result",
        "status":"PASS" if not problems else "FAIL",
        "qa":qa,
        "groundwater_feature_file":str(work / "groundwater_history_features.parquet"),
        "surfacewater_feature_file":str(work / "surfacewater_history_features.parquet"),
        "field_feature_file":str(final_path),
        "flowstats":{
            "file":str(flow_path),
            "sha256":sha256(flow_path),
            "documented_reference_period":cfg["shype_flowstats"]["documented_reference_period"],
            **flow_info,
        },
        "nadia_d2_prep":nadia,
        "guardrails":cfg["guardrails"],
        "problems":problems,
    }
    atomic_json(work / "d_summary.json", summary)

    print("\nQA COVERAGE")
    for k,v in qa.items():
        if k.endswith("_pct"):
            print(f"  {k:30s}: {v:.3f}%")
        else:
            print(f"  {k:30s}: {v:,}")

    # A few non-score descriptive distributions useful for the next design step.
    print("\nRAW FEATURE DISTRIBUTIONS · NO SCORE")
    for col in (
        "gw_small_situation_le10_max_run_days",
        "gw_small_fill_summer_p10",
        "sw_MLQ_MQ_ratio_total",
        "sw_MLQ_total_m3s",
        "sw_MLQ_total_lps_km2_upstream",
    ):
        if col not in final.columns:
            continue
        x = pd.to_numeric(final[col], errors="coerce").dropna()
        if x.empty:
            continue
        print(
            f"  {col}: n={len(x):,} · "
            f"P10={x.quantile(.10):.4g} · P50={x.median():.4g} · "
            f"P90={x.quantile(.90):.4g}"
        )

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -", p)

    print("\nOutputs:", work)
    print("=" * 122)
    print(f"AKERVATTEN STOPPUNKT D HISTORICAL RAW FEATURES: {summary['status']}")
    print("No composite score has been frozen.")
    print("=" * 122)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
