#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import shutil
import tempfile

import geopandas as gpd

BASE = "https://epub.sjv.se/inspire/inspire/wfs"


def main():
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "inspire:arslager_block",
        "CQL_FILTER": "arslager=2025 AND region_kod LIKE '1233%'",
        "format_options": "CHARSET:UTF-8",
        "outputFormat": "gpkg",
    }
    url = BASE + "?" + urlencode(params)
    print("=" * 72)
    print("ÅkerSync · Jordbruksverket WFS-probe · Vellinge 2025")
    print("=" * 72)
    print("Hämtar block för kommunprefix 1233 ...")

    req = Request(url, headers={"User-Agent": "AkerSync/0.92"})
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "vellinge_blocks.gpkg"
        with urlopen(req, timeout=180) as r, open(p, "wb") as f:
            shutil.copyfileobj(r, f)
        print(f"Nedladdat: {p.stat().st_size/1024/1024:.1f} MB")
        try:
            g = gpd.read_file(p)
        except Exception:
            head = p.read_bytes()[:500]
            print("Kunde inte läsa svaret som GeoPackage. Första bytes:")
            print(head.decode("utf-8", errors="replace"))
            raise

        print(f"Rader: {len(g):,}")
        print("Kolumner:", ", ".join(g.columns))
        if "region_kod" in g.columns:
            vals = sorted(g.region_kod.astype(str).unique())
            print("region_kod exempel:", vals[:10])
        if "arslager" in g.columns:
            print("arslager:", sorted(g.arslager.astype(str).unique())[:10])
        if len(g):
            print("Bounds EPSG/native:", [round(float(x), 2) for x in g.total_bounds])
            print("PROBE: OK — WFS returnerar Vellinge-block.")
        else:
            print("PROBE: 0 RADER — WFS/filter behöver granskas.")


if __name__ == "__main__":
    main()
