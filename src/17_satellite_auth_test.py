#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Satellite V1a — authenticate to Copernicus Data Space openEO.

This step deliberately downloads no EO pixels.  It only verifies that the local
machine can authenticate to the CDSE openEO backend and that SENTINEL2_L2A is
available.  The first run normally prints a browser URL for the OIDC device
flow; later runs reuse the stored refresh token when possible.
"""
from __future__ import annotations

import sys

BACKEND = "https://openeo.dataspace.copernicus.eu"
COLLECTION = "SENTINEL2_L2A"


def main() -> int:
    try:
        import openeo
    except ImportError as e:
        raise SystemExit(
            "Python-paketet 'openeo' saknas. Kör SATELLITE_AUTH_TEST.bat; "
            "den installerar paketet automatiskt."
        ) from e

    print("=" * 92)
    print("ÅkerSync · Satellite V1a · Copernicus openEO auth test")
    print("=" * 92)
    print("Backend:", BACKEND)
    print("Ingen satellitdata laddas ner i detta steg.")
    print()

    con = openeo.connect(BACKEND)
    print("Ansluten till openEO. Autentiserar …")
    print("Första gången kan du få en URL/kod: öppna länken i valfri webbläsare och logga in på CDSE.")
    con.authenticate_oidc()
    print("Autentisering: OK")

    # Avoid printing account details; just verify authenticated account access.
    try:
        account = con.describe_account()
        if not isinstance(account, dict):
            raise RuntimeError("Oväntat svar från describe_account")
        print("Kontot kan läsas: OK")
    except Exception as e:
        raise RuntimeError(f"Autentiserad men kunde inte läsa kontostatus: {e}") from e

    print(f"Kontrollerar collection {COLLECTION} …")
    try:
        desc = con.describe_collection(COLLECTION)
    except Exception as e:
        raise RuntimeError(f"Kunde inte läsa {COLLECTION}: {e}") from e

    bands = []
    for cube_dim in (desc.get("cube:dimensions", {}) or {}).values():
        vals = cube_dim.get("values") if isinstance(cube_dim, dict) else None
        if isinstance(vals, list):
            bands.extend(str(v) for v in vals)
    bands_upper = {b.upper() for b in bands}
    # Some backends expose band names in summaries rather than dimension values;
    # collection existence is the hard requirement, band listing is only a sanity check.
    wanted = {"B04", "B08", "SCL"}
    if bands_upper:
        print("B04/B08/SCL annonserade:", wanted.issubset(bands_upper))
    else:
        print("Bandlista ej exponerad i väntat metadatafält; collection finns ändå.")

    print()
    print("SATELLITE AUTH: OK")
    print("Nästa steg: liten Sentinel-2 pixel-PoC över Lomma, inte hela Skåne.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
