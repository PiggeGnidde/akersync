#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch official Jordbruksverket 2026 winter-rapeseed (Höstraps) norm yields from PXWeb."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from fetch_normskord_havre_2026 import (
    SKO_DOMAIN, API_URL, http_json, find_var, value_code,
    flatten_jsonstat2, parse_sko_id,
)

CROP_LABEL = "Höstraps"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--api-url", default=API_URL)
    args = ap.parse_args()

    print("Fetching PXWeb metadata:", args.api_url)
    meta = http_json(args.api_url)
    v_sko = find_var(meta, "Skördeområde")
    v_year = find_var(meta, "År")
    v_crop = find_var(meta, "Gröda")
    v_var = find_var(meta, "Variabel")

    year_code = value_code(v_year, "2026")
    crop_code = value_code(v_crop, CROP_LABEL)
    query = {
        "query": [
            {"code": v_sko["code"], "selection": {"filter": "all", "values": ["*"]}},
            {"code": v_year["code"], "selection": {"filter": "item", "values": [year_code]}},
            {"code": v_crop["code"], "selection": {"filter": "item", "values": [crop_code]}},
            {"code": v_var["code"], "selection": {"filter": "all", "values": ["*"]}},
        ],
        "response": {"format": "json-stat2"},
    }
    print("Fetching official 2026 Höstraps SKO table...")
    rows = flatten_jsonstat2(http_json(args.api_url, query))

    by_sko = {s: {"sko_id": s, "norm_kg_ha": "", "n_companies": ""} for s in SKO_DOMAIN}
    for r in rows:
        sko = parse_sko_id(r.get(v_sko["code"], ""))
        if sko not in by_sko:
            continue
        var_text = str(r.get(v_var["code"], "")).lower()
        val = r.get("value")
        if val is None:
            continue
        if "normskörd" in var_text and "kg" in var_text:
            by_sko[sko]["norm_kg_ha"] = int(round(float(val)))
        elif "antal företag" in var_text:
            by_sko[sko]["n_companies"] = int(round(float(val)))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["sko_id", "norm_kg_ha", "n_companies", "source_note"])
        w.writeheader()
        for sko in SKO_DOMAIN:
            rec = dict(by_sko[sko])
            rec["source_note"] = "Jordbruksverket PXWeb JO0602A03, Höstraps, 2026"
            w.writerow(rec)

    published = [(s, by_sko[s]["norm_kg_ha"], by_sko[s]["n_companies"])
                 for s in SKO_DOMAIN if by_sko[s]["norm_kg_ha"] != ""]
    print(f"Published Höstraps norm yield for {len(published)}/{len(SKO_DOMAIN)} domain SKO:")
    for s, y, n in published:
        print(f"  {s}: {y} kg/ha; n_companies={n}")
    if len(published) < 8:
        raise RuntimeError(f"Only {len(published)} published Höstraps SKO values; expected at least 8")
    print("HÖSTRAPS NORMSKÖRD FETCH: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
