#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import pandas as pd

from common import MUN_CODES

BASE = "https://epub.sjv.se/inspire/inspire/wfs"
YEAR = 2025
UA = "AkerSync/0.92"
BBOX_PAD_M = 100.0

BLOCK_INFO = {
    "typename": "inspire:arslager_block",
    "filename": "arslager_block_skane_2025.gpkg",
    "layer": "arslager_block",
    "required": ["arslager", "blockid", "region_kod", "kategori", "agoslag", "areal", "geometry"],
}

SKIFTE_INFO = {
    "typename": "inspire:arslager_skifte",
    "filename": "arslager_skifte_skane_2025.gpkg",
    "layer": "arslager_skifte",
    # Jordbruksverkets skifteslager har INTE region_kod. Kommunen härleds
    # därför via blockid mot det kompletta blocklagret.
    "required_server": [
        "arslager", "blockid", "skiftesbeteckning", "grdkod_mar", "grdkod_und",
        "ansokt_areal_ha", "faststalld_areal_ha", "geometry",
    ],
}


def request_bytes(params, timeout=240, tries=3):
    url = BASE + "?" + urlencode(params)
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except (HTTPError, URLError, TimeoutError) as e:
            last = e
            if attempt == tries:
                break
            wait = 2 * attempt
            print(f"    nätfel ({e}); nytt försök om {wait}s ...")
            time.sleep(wait)
    raise RuntimeError(f"WFS-förfrågan misslyckades efter {tries} försök: {last}")


def block_cql(code):
    return f"arslager={YEAR} AND region_kod LIKE '{code}%'"


def year_cql():
    return f"arslager={YEAR}"


def skifte_bbox_cql(x0, y0, x1, y1):
    """One CQL filter containing both year and spatial restriction.

    Jordbruksverkets GeoServer rejects simultaneous BBOX= and CQL_FILTER=
    query parameters. The skifte feature type uses the geometry property
    name 'geom', so put BBOX inside CQL instead.
    """
    return (
        f"arslager={YEAR} AND "
        f"BBOX(geom,{x0:.3f},{y0:.3f},{x1:.3f},{y1:.3f},'EPSG:3006')"
    )


def _parse_hits(raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    for k, v in root.attrib.items():
        key = k.lower()
        if key.endswith("numbermatched") or key.endswith("numberoffeatures"):
            try:
                return int(v)
            except ValueError:
                pass
    return None


def hit_count_query(typename, cql_filter, bbox=None):
    """Return a reliable positive WFS hit count when the service provides one."""
    for version in ("2.0.0", "1.1.0", "1.0.0"):
        params = {
            "SERVICE": "WFS",
            "VERSION": version,
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "CQL_FILTER": cql_filter,
            "RESULTTYPE": "hits",
        }
        if bbox is not None:
            params["BBOX"] = bbox
        try:
            n = _parse_hits(request_bytes(params, timeout=120))
        except Exception:
            continue
        # This endpoint has returned zero for valid WFS 1.0 hits queries.
        # Positive counts are useful; zero is treated as unavailable.
        if n is not None and n > 0:
            return n, version
    return None, None


def download_gpkg_query(typename, path, cql_filter, bbox=None):
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "CQL_FILTER": cql_filter,
        "format_options": "CHARSET:UTF-8",
        "outputFormat": "gpkg",
        "SRSNAME": "EPSG:3006",
    }
    if bbox is not None:
        params["BBOX"] = bbox
    raw = request_bytes(params)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.gpkg")
    tmp.write_bytes(raw)
    try:
        g = gpd.read_file(tmp)
    except Exception:
        head = raw[:1000].decode("utf-8", errors="replace")
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Svaret för {typename} var inte en läsbar GeoPackage.\n{head}")
    if path.exists():
        path.unlink()
    tmp.replace(path)
    return g


def validate_block_part(g, code, expected):
    missing = [c for c in BLOCK_INFO["required"] if c not in g.columns]
    if missing:
        raise RuntimeError(f"{BLOCK_INFO['typename']} {code}: saknar kolumner {missing}; fick {list(g.columns)}")
    if expected is not None and len(g) != expected:
        raise RuntimeError(
            f"{BLOCK_INFO['typename']} {code}: WFS hits={expected:,}, GeoPackage={len(g):,}. "
            "Avbryter för att undvika tyst trunkering."
        )
    if len(g) == 0:
        raise RuntimeError(f"{BLOCK_INFO['typename']} {code}: 0 rader")
    reg = g["region_kod"].astype(str)
    if not reg.str.startswith(code).all():
        bad = sorted(reg[~reg.str.startswith(code)].unique())[:10]
        raise RuntimeError(f"{BLOCK_INFO['typename']} {code}: oväntade region_kod {bad}")
    years = set(g["arslager"].astype(str))
    if years != {str(YEAR)}:
        raise RuntimeError(f"{BLOCK_INFO['typename']} {code}: oväntade årslager {sorted(years)}")
    if g.crs is None:
        raise RuntimeError(f"{BLOCK_INFO['typename']} {code}: CRS saknas")
    if g.geometry.isna().all() or g.geometry.is_empty.all():
        raise RuntimeError(f"{BLOCK_INFO['typename']} {code}: alla geometrier saknas/tomma")


def validate_skifte_candidate(g, expected):
    missing = [c for c in SKIFTE_INFO["required_server"] if c not in g.columns]
    if missing:
        raise RuntimeError(f"{SKIFTE_INFO['typename']}: saknar kolumner {missing}; fick {list(g.columns)}")
    if expected is not None and len(g) != expected:
        raise RuntimeError(
            f"{SKIFTE_INFO['typename']}: bbox-hits={expected:,}, GeoPackage={len(g):,}. "
            "Avbryter för att undvika tyst trunkering."
        )
    years = set(g["arslager"].astype(str))
    if years != {str(YEAR)}:
        raise RuntimeError(f"{SKIFTE_INFO['typename']}: oväntade årslager {sorted(years)}")
    if g.crs is None:
        raise RuntimeError(f"{SKIFTE_INFO['typename']}: CRS saknas")
    if len(g) and (g.geometry.isna().all() or g.geometry.is_empty.all()):
        raise RuntimeError(f"{SKIFTE_INFO['typename']}: alla geometrier saknas/tomma")


def validate_skifte_part(g, code, allowed_blockids):
    required = SKIFTE_INFO["required_server"] + ["region_kod"]
    missing = [c for c in required if c not in g.columns]
    if missing:
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: saknar kolumner {missing}")
    if len(g) == 0:
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: 0 skiften efter blockkoppling")
    ids = g["blockid"].astype(str)
    bad_ids = sorted(set(ids) - allowed_blockids)
    if bad_ids:
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: {len(bad_ids)} blockid hör inte till kommunen; exempel {bad_ids[:10]}")
    reg = g["region_kod"].astype(str)
    if not reg.str.startswith(code).all():
        bad = sorted(reg[~reg.str.startswith(code)].unique())[:10]
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: oväntade härledda region_kod {bad}")
    years = set(g["arslager"].astype(str))
    if years != {str(YEAR)}:
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: oväntade årslager {sorted(years)}")
    if g.crs is None:
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: CRS saknas")
    if g.geometry.isna().all() or g.geometry.is_empty.all():
        raise RuntimeError(f"{SKIFTE_INFO['typename']} {code}: alla geometrier saknas/tomma")


def fetch_blocks(outdir, resume=True):
    parts_dir = outdir / "parts" / "blocks"
    parts = []
    counts = {}
    print("\n" + "=" * 78)
    print("Jordbruksverket 2025 · blocks")
    print("=" * 78)

    for i, (name, code) in enumerate(MUN_CODES.items(), 1):
        expected, hits_version = hit_count_query(BLOCK_INFO["typename"], block_cql(code))
        exp_txt = "? (hits opålitlig/ej tillgänglig)" if expected is None else f"{expected:,} (WFS {hits_version})"
        p = parts_dir / f"{code}_blocks.gpkg"
        print(f"[{i:02d}/33] {name:<15} {code}  hits={exp_txt}", end="")

        g = None
        if resume and p.exists():
            try:
                candidate = gpd.read_file(p)
                validate_block_part(candidate, code, expected)
                g = candidate
                print(f"  cache OK ({len(g):,} rader)")
            except Exception as e:
                print(f"  cache ogiltig ({e}); hämtar om")
                p.unlink(missing_ok=True)
        if g is None:
            g = download_gpkg_query(BLOCK_INFO["typename"], p, block_cql(code))
            validate_block_part(g, code, expected)
            suffix = "" if expected is not None else "; hits ej användbar, år/kommun/geometri OK"
            print(f"  hämtad {len(g):,} rader, {p.stat().st_size/1024/1024:.1f} MB{suffix}")

        counts[name] = {
            "code": code,
            "rows": int(len(g)),
            "wfs_hits": expected,
            "wfs_hits_version": hits_version,
        }
        parts.append(g)

    crs = parts[0].crs
    for g in parts[1:]:
        if g.crs != crs:
            raise RuntimeError(f"blocks: blandade CRS: {crs} och {g.crs}")
    merged = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=crs)

    out = outdir / BLOCK_INFO["filename"]
    if out.exists():
        out.unlink()
    merged.to_file(out, layer=BLOCK_INFO["layer"], driver="GPKG")
    check = gpd.read_file(out)
    if len(check) != len(merged):
        raise RuntimeError(f"blocks: merge-verifiering misslyckades {len(check):,}!={len(merged):,}")

    print(f"\nblocks: TOTAL {len(merged):,} rader")
    print(f"blocks: {out} ({out.stat().st_size/1024/1024:.1f} MB)")
    return out, merged, counts


def fetch_skiften(outdir, blocks, resume=True):
    """Fetch skiften by municipality block extent, then assign municipality by blockid.

    arslager_skifte does not expose region_kod, so CQL region filtering is invalid.
    Jordbruksverkets GeoServer also rejects BBOX and CQL_FILTER as two separate
    request parameters. We therefore combine year + BBOX(geom, ...) into one
    CQL filter, then retain only skiften whose blockid belongs to the municipality.
    """
    parts_dir = outdir / "parts" / "skiften"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    counts = {}
    block_region = blocks[["blockid", "region_kod"]].copy()
    block_region["blockid_s"] = block_region.blockid.astype(str)
    conflicts = block_region.groupby("blockid_s").region_kod.nunique()
    if int((conflicts > 1).sum()) != 0:
        raise RuntimeError("Samma blockid förekommer med flera region_kod i blocklagret.")
    region_map = block_region.drop_duplicates("blockid_s").set_index("blockid_s").region_kod.astype(str).to_dict()

    print("\n" + "=" * 78)
    print("Jordbruksverket 2025 · skiften")
    print("=" * 78)
    print("Obs: skifteslagret saknar region_kod; kommun härleds via blockid.")
    print("Spatialt urval: år + BBOX(geom, ...) i samma CQL-filter.")

    all_regions = blocks.region_kod.astype(str)
    for i, (name, code) in enumerate(MUN_CODES.items(), 1):
        b = blocks[all_regions.str.startswith(code)].copy()
        if b.empty:
            raise RuntimeError(f"Inga block för {name} ({code}) i det kompletta blocklagret")
        allowed = set(b.blockid.astype(str))
        x0, y0, x1, y1 = [float(v) for v in b.total_bounds]
        qx0 = x0 - BBOX_PAD_M
        qy0 = y0 - BBOX_PAD_M
        qx1 = x1 + BBOX_PAD_M
        qy1 = y1 + BBOX_PAD_M
        bbox_label = f"{qx0:.3f},{qy0:.3f},{qx1:.3f},{qy1:.3f},EPSG:3006"
        spatial_cql = skifte_bbox_cql(qx0, qy0, qx1, qy1)
        expected, hits_version = hit_count_query(SKIFTE_INFO["typename"], spatial_cql)
        exp_txt = "? (hits opålitlig/ej tillgänglig)" if expected is None else f"{expected:,} (WFS {hits_version})"
        p = parts_dir / f"{code}_skiften.gpkg"
        meta = parts_dir / f"{code}_skiften.json"
        print(f"[{i:02d}/33] {name:<15} {code}  cql-bbox-hits={exp_txt}", end="")

        g = None
        cached_meta = {}
        if resume and p.exists():
            try:
                candidate = gpd.read_file(p)
                validate_skifte_part(candidate, code, allowed)
                g = candidate
                if meta.exists():
                    cached_meta = json.loads(meta.read_text(encoding="utf-8"))
                print(f"  cache OK ({len(g):,} skiften)")
            except Exception as e:
                print(f"  cache ogiltig ({e}); hämtar om")
                p.unlink(missing_ok=True)
                meta.unlink(missing_ok=True)

        candidate_rows = cached_meta.get("candidate_rows")
        if g is None:
            cand_path = parts_dir / f"{code}_skiften_bbox_candidate.gpkg"
            cand = download_gpkg_query(SKIFTE_INFO["typename"], cand_path, spatial_cql)
            validate_skifte_candidate(cand, expected)
            candidate_rows = int(len(cand))
            ids = cand.blockid.astype(str)
            g = cand[ids.isin(allowed)].copy()
            g["region_kod"] = g.blockid.astype(str).map(region_map)
            validate_skifte_part(g, code, allowed)
            if p.exists():
                p.unlink()
            g.to_file(p, driver="GPKG")
            cand_path.unlink(missing_ok=True)
            meta.write_text(json.dumps({
                "code": code,
                "bbox": bbox_label,
                "cql_filter": spatial_cql,
                "candidate_rows": candidate_rows,
                "bbox_wfs_hits": expected,
                "bbox_wfs_hits_version": hits_version,
                "kept_rows": int(len(g)),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  kandidat {candidate_rows:,} -> {len(g):,} skiften, {p.stat().st_size/1024/1024:.1f} MB")

        counts[name] = {
            "code": code,
            "rows": int(len(g)),
            "bbox_candidate_rows": candidate_rows,
            "bbox_wfs_hits": expected,
            "bbox_wfs_hits_version": hits_version,
        }
        parts.append(g)

    crs = parts[0].crs
    for g in parts[1:]:
        if g.crs != crs:
            raise RuntimeError(f"skiften: blandade CRS: {crs} och {g.crs}")
    merged = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=crs)

    out = outdir / SKIFTE_INFO["filename"]
    if out.exists():
        out.unlink()
    merged.to_file(out, layer=SKIFTE_INFO["layer"], driver="GPKG")
    check = gpd.read_file(out)
    if len(check) != len(merged):
        raise RuntimeError(f"skiften: merge-verifiering misslyckades {len(check):,}!={len(merged):,}")

    print(f"\nskiften: TOTAL {len(merged):,} rader")
    print(f"skiften: {out} ({out.stat().st_size/1024/1024:.1f} MB)")
    return out, merged, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\AkerSyncRaw\jv_skane_2025")
    ap.add_argument("--no-resume", action="store_true")
    a = ap.parse_args()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("ÅkerSync · komplett Jordbruksverket-rådata · Skåne 2025")
    print("=" * 78)
    print("Källa:", BASE)
    print("Output:", outdir)
    print("Strategi: block per kommun; skiften via CQL year+BBOX + lokal blockid-koppling; resumable cache")

    bpath, blocks, bcounts = fetch_blocks(outdir, resume=not a.no_resume)
    spath, skiften, scounts = fetch_skiften(outdir, blocks, resume=not a.no_resume)

    blockids = set(blocks.blockid.astype(str))
    sblockids = set(skiften.blockid.astype(str))
    orphan = sblockids - blockids
    if orphan:
        sample = sorted(orphan)[:20]
        raise RuntimeError(f"Skiften refererar till {len(orphan):,} block som saknas i blockfilen. Exempel: {sample}")

    manifest = {
        "year": YEAR,
        "source": BASE,
        "blocks": {"path": str(bpath), "rows": int(len(blocks)), "municipalities": bcounts},
        "skiften": {"path": str(spath), "rows": int(len(skiften)), "municipalities": scounts},
        "orphan_skifte_blockids": 0,
        "notes": [
            "arslager_skifte saknar region_kod; kommun härleds via blockid mot arslager_block.",
            "Skiften hämtas med ett kombinerat CQL-filter: arslager + BBOX(geom,...), eftersom tjänsten avvisar separata BBOX- och CQL_FILTER-parametrar.",
            "BBox-kandidater filtreras lokalt på kommunens blockid.",
            "Positiva WFS hits används som trunceringskontroll när tjänsten ger tillförlitligt resultat.",
        ],
    }
    mpath = outdir / "manifest_skane_2025.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print("KLART · komplett Skåne-rådata 2025")
    print("=" * 78)
    print(f"Block:   {len(blocks):,}")
    print(f"Skiften: {len(skiften):,}")
    print("Orphan skifte->block: 0")
    print("Manifest:", mpath)
    print("\nNästa steg: SET_JV_SKANE_2025.bat")


if __name__ == "__main__":
    main()
