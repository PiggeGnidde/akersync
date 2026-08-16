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

LAYERS = {
    "blocks": {
        "typename": "inspire:arslager_block",
        "filename": "arslager_block_skane_2025.gpkg",
        "layer": "arslager_block",
        "required": ["arslager", "blockid", "region_kod", "kategori", "agoslag", "areal", "geometry"],
    },
    "skiften": {
        "typename": "inspire:arslager_skifte",
        "filename": "arslager_skifte_skane_2025.gpkg",
        "layer": "arslager_skifte",
        "required": [
            "arslager", "blockid", "region_kod", "skiftesbeteckning",
            "grdkod_mar", "grdkod_und", "ansokt_areal_ha",
            "faststalld_areal_ha", "geometry",
        ],
    },
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


def cql(code):
    return f"arslager={YEAR} AND region_kod LIKE '{code}%'"


def hit_count(typename, code):
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "CQL_FILTER": cql(code),
        "RESULTTYPE": "hits",
    }
    raw = request_bytes(params, timeout=120)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    for k, v in root.attrib.items():
        if k.lower().endswith("numberoffeatures") or k.lower().endswith("numbermatched"):
            try:
                return int(v)
            except ValueError:
                pass
    return None


def download_gpkg(typename, code, path):
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "CQL_FILTER": cql(code),
        "format_options": "CHARSET:UTF-8",
        "outputFormat": "gpkg",
    }
    raw = request_bytes(params)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.gpkg")
    tmp.write_bytes(raw)
    try:
        g = gpd.read_file(tmp)
    except Exception:
        head = raw[:1000].decode("utf-8", errors="replace")
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Svaret för {typename} {code} var inte en läsbar GeoPackage.\n{head}")
    if path.exists():
        path.unlink()
    tmp.replace(path)
    return g


def validate_part(g, info, code, expected):
    missing = [c for c in info["required"] if c not in g.columns]
    if missing:
        raise RuntimeError(f"{info['typename']} {code}: saknar kolumner {missing}; fick {list(g.columns)}")
    if expected is not None and len(g) != expected:
        raise RuntimeError(
            f"{info['typename']} {code}: WFS hits={expected:,}, GeoPackage={len(g):,}. "
            "Avbryter för att undvika tyst trunkering."
        )
    if len(g) == 0:
        raise RuntimeError(f"{info['typename']} {code}: 0 rader")
    reg = g["region_kod"].astype(str)
    if not reg.str.startswith(code).all():
        bad = sorted(reg[~reg.str.startswith(code)].unique())[:10]
        raise RuntimeError(f"{info['typename']} {code}: oväntade region_kod {bad}")
    years = set(g["arslager"].astype(str))
    if years != {str(YEAR)}:
        raise RuntimeError(f"{info['typename']} {code}: oväntade årslager {sorted(years)}")
    if g.crs is None:
        raise RuntimeError(f"{info['typename']} {code}: CRS saknas")


def fetch_layer(kind, outdir, resume=True):
    info = dict(LAYERS[kind])
    parts_dir = outdir / "parts" / kind
    parts = []
    counts = {}
    print("\n" + "=" * 78)
    print(f"Jordbruksverket 2025 · {kind}")
    print("=" * 78)

    for i, (name, code) in enumerate(MUN_CODES.items(), 1):
        expected = hit_count(info["typename"], code)
        exp_txt = "?" if expected is None else f"{expected:,}"
        p = parts_dir / f"{code}_{kind}.gpkg"
        print(f"[{i:02d}/33] {name:<15} {code}  hits={exp_txt}", end="")

        g = None
        if resume and p.exists():
            try:
                candidate = gpd.read_file(p)
                validate_part(candidate, info, code, expected)
                g = candidate
                print("  cache OK")
            except Exception as e:
                print(f"  cache ogiltig ({e}); hämtar om")
                p.unlink(missing_ok=True)
        if g is None:
            g = download_gpkg(info["typename"], code, p)
            validate_part(g, info, code, expected)
            print(f"  hämtad {len(g):,} rader, {p.stat().st_size/1024/1024:.1f} MB")

        counts[name] = {"code": code, "rows": int(len(g)), "wfs_hits": expected}
        parts.append(g)

    crs = parts[0].crs
    for g in parts[1:]:
        if g.crs != crs:
            raise RuntimeError(f"{kind}: blandade CRS: {crs} och {g.crs}")
    merged = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=crs)

    out = outdir / info["filename"]
    if out.exists():
        out.unlink()
    merged.to_file(out, layer=info["layer"], driver="GPKG")
    check = gpd.read_file(out)
    if len(check) != len(merged):
        raise RuntimeError(f"{kind}: merge-verifiering misslyckades {len(check):,}!={len(merged):,}")

    print(f"\n{kind}: TOTAL {len(merged):,} rader")
    print(f"{kind}: {out} ({out.stat().st_size/1024/1024:.1f} MB)")
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
    print("Strategi: 33 kommunfilter per lager + WFS hits-kontroll + resumable cache")

    bpath, blocks, bcounts = fetch_layer("blocks", outdir, resume=not a.no_resume)
    spath, skiften, scounts = fetch_layer("skiften", outdir, resume=not a.no_resume)

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
