#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd

from common import sha256_file

BASE = "https://epub.sjv.se/inspire/inspire/wfs"
UA = "AkerSync-AkerMinne/1a"
SRS = "EPSG:3006"
BBOX_PAD_M = 100.0
DEFAULT_YEARS = (2015, 2020)
DEFAULT_MUNICIPALITY = "Skurup"
DEFAULT_MUNICIPALITY_CODE = "1264"

BLOCK_TYPENAME = "inspire:arslager_block"
SKIFTE_TYPENAME = "inspire:arslager_skifte"
BLOCK_LAYER = "arslager_block"
SKIFTE_LAYER = "arslager_skifte"

BLOCK_REQUIRED = ("arslager", "blockid", "region_kod", "geometry")
SKIFTE_REQUIRED_SERVER = (
    "arslager", "blockid", "skiftesbeteckning", "grdkod_mar", "grdkod_und",
    "ansokt_areal_ha", "faststalld_areal_ha", "geometry",
)


def request_bytes(params: dict[str, object], timeout: int = 240, tries: int = 3) -> bytes:
    url = BASE + "?" + urlencode(params)
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            if attempt == tries:
                break
            wait_s = 2 * attempt
            print(f"    nätfel ({exc}); nytt försök om {wait_s}s ...")
            time.sleep(wait_s)
    raise RuntimeError(f"WFS-förfrågan misslyckades efter {tries} försök: {last}")


def block_cql(year: int, municipality_code: str) -> str:
    return f"arslager={int(year)} AND region_kod LIKE '{municipality_code}%'"


def skifte_bbox_cql(year: int, bounds: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = bounds
    return (
        f"arslager={int(year)} AND "
        f"BBOX(geom,{x0:.3f},{y0:.3f},{x1:.3f},{y1:.3f},'{SRS}')"
    )


def _parse_hits(raw: bytes) -> int | None:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    for key, value in root.attrib.items():
        low = key.lower()
        if low.endswith("numbermatched") or low.endswith("numberoffeatures"):
            try:
                return int(value)
            except ValueError:
                pass
    return None


def hit_count_query(typename: str, cql_filter: str) -> tuple[int | None, str | None]:
    for version in ("2.0.0", "1.1.0", "1.0.0"):
        params = {
            "SERVICE": "WFS",
            "VERSION": version,
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "CQL_FILTER": cql_filter,
            "RESULTTYPE": "hits",
        }
        try:
            count = _parse_hits(request_bytes(params, timeout=120))
        except Exception:
            continue
        if count is not None and count > 0:
            return count, version
    return None, None


def download_gpkg(typename: str, path: Path, cql_filter: str) -> gpd.GeoDataFrame:
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "CQL_FILTER": cql_filter,
        "format_options": "CHARSET:UTF-8",
        "outputFormat": "gpkg",
        "SRSNAME": SRS,
    }
    raw = request_bytes(params)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".download.tmp.gpkg")
    tmp.write_bytes(raw)
    try:
        gdf = gpd.read_file(tmp)
    except Exception:
        head = raw[:1000].decode("utf-8", errors="replace")
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Svaret för {typename} var inte en läsbar GeoPackage.\n{head}")
    tmp.unlink(missing_ok=True)
    return gdf


def _require_columns(gdf: gpd.GeoDataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [column for column in required if column not in gdf.columns]
    if missing:
        raise RuntimeError(f"{label}: saknar kolumner {missing}; fick {list(gdf.columns)}")


def _validate_geometry(gdf: gpd.GeoDataFrame, label: str) -> None:
    if gdf.crs is None:
        raise RuntimeError(f"{label}: CRS saknas")
    if len(gdf) == 0:
        raise RuntimeError(f"{label}: 0 rader")
    if gdf.geometry.isna().all() or gdf.geometry.is_empty.all():
        raise RuntimeError(f"{label}: alla geometrier saknas/tomma")


def validate_blocks(gdf: gpd.GeoDataFrame, year: int, municipality_code: str) -> None:
    _require_columns(gdf, BLOCK_REQUIRED, "block")
    _validate_geometry(gdf, "block")
    years = set(gdf["arslager"].astype(str))
    if years != {str(year)}:
        raise RuntimeError(f"block: oväntade årslager {sorted(years)}")
    regions = gdf["region_kod"].astype(str)
    if not regions.str.startswith(municipality_code).all():
        bad = sorted(regions[~regions.str.startswith(municipality_code)].unique())[:10]
        raise RuntimeError(f"block: oväntade region_kod {bad}")
    if gdf["blockid"].astype(str).duplicated().any():
        raise RuntimeError("block: duplicerade blockid i pilotuttaget")


def filter_skiften_to_blocks(
    candidates: gpd.GeoDataFrame,
    blocks: gpd.GeoDataFrame,
    year: int,
    municipality_code: str,
) -> gpd.GeoDataFrame:
    _require_columns(candidates, SKIFTE_REQUIRED_SERVER, "skifte kandidat")
    _validate_geometry(candidates, "skifte kandidat")
    years = set(candidates["arslager"].astype(str))
    if years != {str(year)}:
        raise RuntimeError(f"skifte kandidat: oväntade årslager {sorted(years)}")

    block_map = (
        blocks.assign(blockid_s=blocks["blockid"].astype(str))
        .drop_duplicates("blockid_s")
        .set_index("blockid_s")["region_kod"]
        .astype(str)
        .to_dict()
    )
    ids = candidates["blockid"].astype(str)
    out = candidates.loc[ids.isin(block_map)].copy()
    if out.empty:
        raise RuntimeError("skifte: 0 rader efter blockid-koppling")
    out["region_kod"] = out["blockid"].astype(str).map(block_map)
    if not out["region_kod"].astype(str).str.startswith(municipality_code).all():
        raise RuntimeError("skifte: region_kod-koppling gav rader utanför pilotkommunen")
    return out


def _write_verified(gdf: gpd.GeoDataFrame, path: Path, layer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".write.tmp.gpkg")
    tmp.unlink(missing_ok=True)
    gdf.to_file(tmp, layer=layer, driver="GPKG")
    check = gpd.read_file(tmp, layer=layer)
    if len(check) != len(gdf):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{path.name}: skrivverifiering {len(check):,}!={len(gdf):,}")
    if path.exists():
        path.unlink()
    tmp.replace(path)


def _dataset_manifest(path: Path, gdf: gpd.GeoDataFrame, layer: str) -> dict[str, object]:
    valid = gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid
    return {
        "path": str(path),
        "layer": layer,
        "rows": int(len(gdf)),
        "crs": str(gdf.crs),
        "columns": [str(c) for c in gdf.columns if c != "geometry"],
        "valid_geometry_rows": int(valid.sum()),
        "invalid_or_empty_geometry_rows": int(len(gdf) - valid.sum()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def download_year(
    out_root: Path,
    year: int,
    municipality: str,
    municipality_code: str,
    resume: bool = True,
) -> dict[str, object]:
    year_dir = out_root / str(year)
    safe_mun = municipality.lower().replace(" ", "_")
    block_path = year_dir / f"arslager_block_{safe_mun}_{year}.gpkg"
    skifte_path = year_dir / f"arslager_skifte_{safe_mun}_{year}.gpkg"
    manifest_path = year_dir / f"manifest_{safe_mun}_{year}.json"

    print("\n" + "=" * 78)
    print(f"ÅkerMinne pilot · {municipality} · {year}")
    print("=" * 78)

    block_filter = block_cql(year, municipality_code)
    block_hits, block_hits_version = hit_count_query(BLOCK_TYPENAME, block_filter)
    blocks: gpd.GeoDataFrame | None = None
    if resume and block_path.exists():
        try:
            blocks = gpd.read_file(block_path, layer=BLOCK_LAYER)
            validate_blocks(blocks, year, municipality_code)
            print(f"block: cache OK ({len(blocks):,} rader)")
        except Exception as exc:
            print(f"block: cache ogiltig ({exc}); hämtar om")
            block_path.unlink(missing_ok=True)
            blocks = None
    if blocks is None:
        blocks = download_gpkg(BLOCK_TYPENAME, block_path, block_filter)
        validate_blocks(blocks, year, municipality_code)
        if block_hits is not None and len(blocks) != block_hits:
            raise RuntimeError(f"block: WFS hits={block_hits:,}, data={len(blocks):,}; möjlig trunkering")
        _write_verified(blocks, block_path, BLOCK_LAYER)
        print(f"block: hämtad {len(blocks):,} rader")

    x0, y0, x1, y1 = [float(v) for v in blocks.total_bounds]
    padded = (x0 - BBOX_PAD_M, y0 - BBOX_PAD_M, x1 + BBOX_PAD_M, y1 + BBOX_PAD_M)
    skifte_filter = skifte_bbox_cql(year, padded)
    skifte_hits, skifte_hits_version = hit_count_query(SKIFTE_TYPENAME, skifte_filter)
    skiften: gpd.GeoDataFrame | None = None
    candidate_rows: int | None = None
    if resume and skifte_path.exists():
        try:
            skiften = gpd.read_file(skifte_path, layer=SKIFTE_LAYER)
            _require_columns(skiften, SKIFTE_REQUIRED_SERVER + ("region_kod",), "skifte cache")
            _validate_geometry(skiften, "skifte cache")
            if set(skiften["arslager"].astype(str)) != {str(year)}:
                raise RuntimeError("fel årslager")
            allowed = set(blocks["blockid"].astype(str))
            if not skiften["blockid"].astype(str).isin(allowed).all():
                raise RuntimeError("blockid utanför pilotkommunen")
            if manifest_path.exists():
                old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                candidate_rows = old_manifest.get("skiften", {}).get("bbox_candidate_rows")
            print(f"skifte: cache OK ({len(skiften):,} rader)")
        except Exception as exc:
            print(f"skifte: cache ogiltig ({exc}); hämtar om")
            skifte_path.unlink(missing_ok=True)
            skiften = None
    if skiften is None:
        candidates = download_gpkg(SKIFTE_TYPENAME, skifte_path, skifte_filter)
        candidate_rows = int(len(candidates))
        if skifte_hits is not None and candidate_rows != skifte_hits:
            raise RuntimeError(
                f"skifte kandidat: WFS hits={skifte_hits:,}, data={candidate_rows:,}; möjlig trunkering"
            )
        skiften = filter_skiften_to_blocks(candidates, blocks, year, municipality_code)
        _write_verified(skiften, skifte_path, SKIFTE_LAYER)
        print(f"skifte: bbox-kandidat {candidate_rows:,} -> {len(skiften):,} pilotrader")

    year_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema_version": "akerminne-pilot-download-v1a",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": BASE,
        "year": year,
        "municipality": municipality,
        "municipality_code": municipality_code,
        "blocks": {
            **_dataset_manifest(block_path, blocks, BLOCK_LAYER),
            "cql_filter": block_filter,
            "wfs_hits": block_hits,
            "wfs_hits_version": block_hits_version,
        },
        "skiften": {
            **_dataset_manifest(skifte_path, skiften, SKIFTE_LAYER),
            "cql_filter": skifte_filter,
            "bbox_candidate_rows": candidate_rows,
            "bbox_wfs_hits": skifte_hits,
            "bbox_wfs_hits_version": skifte_hits_version,
            "region_kod_note": "Härledd lokalt via blockid mot årets blocklager; originalets skifteslager saknar region_kod.",
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Hämta historisk Skurup-pilotdata för ÅkerMinne v1a")
    parser.add_argument("--out-root", default=r"C:\AkerSyncRaw\akerminne_v1a")
    parser.add_argument("--years", nargs="+", type=int, default=list(DEFAULT_YEARS))
    parser.add_argument("--municipality", default=DEFAULT_MUNICIPALITY)
    parser.add_argument("--municipality-code", default=DEFAULT_MUNICIPALITY_CODE)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    years = sorted(set(args.years))
    if not years:
        raise RuntimeError("Minst ett år krävs")
    unsupported = [year for year in years if year < 2015 or year > 2025]
    if unsupported:
        raise RuntimeError(f"År utanför ÅkerMinne v1a-kontraktet 2015-2025: {unsupported}")

    out_root = Path(args.out_root)
    print("=" * 78)
    print("ÅkerMinne v1a · historisk pilotdata")
    print("=" * 78)
    print("Källa:", BASE)
    print("Kommun:", f"{args.municipality} ({args.municipality_code})")
    print("År:", ", ".join(str(y) for y in years))
    print("Output:", out_root)
    print("Strategi: kommunblock via CQL; skiften via år+BBOX; lokal blockid-koppling; resumable")

    manifests = []
    for year in years:
        manifests.append(download_year(
            out_root=out_root,
            year=year,
            municipality=args.municipality,
            municipality_code=args.municipality_code,
            resume=not args.no_resume,
        ))

    summary = {
        "schema_version": "akerminne-pilot-download-summary-v1a",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": BASE,
        "municipality": args.municipality,
        "municipality_code": args.municipality_code,
        "years": years,
        "results": [
            {
                "year": m["year"],
                "block_rows": m["blocks"]["rows"],
                "skifte_rows": m["skiften"]["rows"],
                "block_sha256": m["blocks"]["sha256"],
                "skifte_sha256": m["skiften"]["sha256"],
            }
            for m in manifests
        ],
    }
    out_root.mkdir(parents=True, exist_ok=True)
    summary_path = out_root / "pilot_download_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print("PILOT DOWNLOAD: PASS")
    print("=" * 78)
    for result in summary["results"]:
        print(f"{result['year']}: block {result['block_rows']:,}; skiften {result['skifte_rows']:,}")
    print("Summary:", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
