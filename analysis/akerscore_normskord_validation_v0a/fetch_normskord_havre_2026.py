#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch official Jordbruksverket 2026 oat norm yields from PXWeb.

The script resolves dimension/value codes from API metadata instead of hardcoding
internal PXWeb numeric codes. Output is restricted to the ÅkerPass Skåne-domain
SKO IDs and keeps published values only; missing/uncertain official values remain
blank.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

SKO_DOMAIN = [
    "0731", "1111", "1112", "1121", "1122", "1123", "1124", "1131",
    "1211", "1212", "1213", "1214", "1215", "1216", "1221", "1222", "1321",
]

API_URL = (
    "https://statistik.sjv.se/PXWeb/api/v1/sv/"
    "Jordbruksverkets%20statistikdatabas/Skordar/Normskord/JO0602A03.px"
)


def http_json(url: str, payload: dict | None = None):
    headers = {"User-Agent": "AkerSync normskord validation/0a"}
    if payload is None:
        req = urllib.request.Request(url, headers=headers)
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def find_var(meta: dict, wanted: str) -> dict:
    wanted_low = wanted.lower()
    for v in meta["variables"]:
        text = " ".join([str(v.get("code", "")), str(v.get("text", ""))]).lower()
        if wanted_low in text:
            return v
    raise RuntimeError(f"Could not identify PXWeb dimension containing {wanted!r}")


def value_code(var: dict, wanted_text: str) -> str:
    wanted = wanted_text.strip().lower()
    for code, text in zip(var.get("values", []), var.get("valueTexts", [])):
        if str(text).strip().lower() == wanted:
            return str(code)
    # relaxed fallback for labels such as '2026' or 'Havre'.
    for code, text in zip(var.get("values", []), var.get("valueTexts", [])):
        if wanted in str(text).strip().lower():
            return str(code)
    raise RuntimeError(f"Could not find value {wanted_text!r} in dimension {var.get('code')}")


def jsonstat_categories(doc: dict, dim_id: str):
    cat = doc["dimension"][dim_id]["category"]
    idx = cat["index"]
    if isinstance(idx, dict):
        ordered = [None] * len(idx)
        for code, pos in idx.items():
            ordered[int(pos)] = code
    else:
        ordered = list(idx)
    labels = cat.get("label", {})
    return ordered, {str(k): str(v) for k, v in labels.items()}


def flatten_jsonstat2(doc: dict):
    ids = list(doc["id"])
    sizes = list(doc["size"])
    values = doc["value"]
    categories = {d: jsonstat_categories(doc, d) for d in ids}
    if isinstance(values, dict):
        dense = [None] * int(__import__("math").prod(sizes))
        for k, v in values.items():
            dense[int(k)] = v
        values = dense

    rows = []
    import itertools
    import numpy as np
    arr = np.asarray(values, dtype=object).reshape(sizes)
    for coord in itertools.product(*[range(n) for n in sizes]):
        row = {}
        for d, pos in zip(ids, coord):
            codes, labels = categories[d]
            code = str(codes[pos])
            row[d] = labels.get(code, code)
            row[d + "__code"] = code
        row["value"] = arr[coord]
        rows.append(row)
    return rows


def parse_sko_id(text: str) -> str | None:
    m = re.search(r"\b(\d{4})\*?\b", str(text))
    return m.group(1) if m else None


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
    crop_code = value_code(v_crop, "Havre")
    query = {
        "query": [
            {"code": v_sko["code"], "selection": {"filter": "all", "values": ["*"]}},
            {"code": v_year["code"], "selection": {"filter": "item", "values": [year_code]}},
            {"code": v_crop["code"], "selection": {"filter": "item", "values": [crop_code]}},
            {"code": v_var["code"], "selection": {"filter": "all", "values": ["*"]}},
        ],
        "response": {"format": "json-stat2"},
    }
    print("Fetching official 2026 Havre SKO table...")
    doc = http_json(args.api_url, query)
    rows = flatten_jsonstat2(doc)

    by_sko = {s: {"sko_id": s, "norm_kg_ha": "", "n_companies": ""} for s in SKO_DOMAIN}
    for r in rows:
        sko_text = r.get(v_sko["code"], "")
        sko = parse_sko_id(sko_text)
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
            rec = by_sko[sko]
            rec["source_note"] = "Jordbruksverket PXWeb JO0602A03, Havre, 2026"
            w.writerow(rec)

    published = [(s, by_sko[s]["norm_kg_ha"], by_sko[s]["n_companies"]) for s in SKO_DOMAIN if by_sko[s]["norm_kg_ha"] != ""]
    print(f"Published Havre norm yield for {len(published)}/{len(SKO_DOMAIN)} domain SKO:")
    for s, y, n in published:
        print(f"  {s}: {y} kg/ha; n_companies={n}")
    if len(published) < 8:
        raise RuntimeError(f"Only {len(published)} published oat SKO values; expected at least 8")
    print("HAVRE NORMSKÖRD FETCH: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
