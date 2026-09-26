#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerVatten MVP v0a · STOPPUNKT A2 official source inventory.

Network inventory only:
- SGU small-aquifer groundwater availability WCS/bulk route
- SGU groundwater-magazine OGC API
- SGU-HYPE OGC API + small sample of area/history schema
- SMHI SVAR2022 geometry WFS/bulk route
- SMHI S-HYPE/Vattenwebb/NADIA documented bulk interface
- license pages

No large source file or long time-series download is performed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "akervatten_mvp_v0a_a2.json"
DEFAULT_WORK = ROOT / "work" / "akervatten_mvp_v0a" / "a2_source_inventory"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def localname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


class Probe:
    def __init__(self, timeout: int, user_agent: str):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def get(self, url: str, *, params: dict[str, Any] | None = None, max_bytes: int = 2_000_000):
        r = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=True)
        r.raise_for_status()
        content = r.content
        if len(content) > max_bytes:
            raise RuntimeError(f"Response too large for source-inventory probe: {len(content):,} bytes from {r.url}")
        return r

    def head_or_range(self, url: str) -> dict[str, Any]:
        # Never consume a large body in A2.
        try:
            r = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            if r.status_code < 400:
                return {
                    "ok": True,
                    "method": "HEAD",
                    "status_code": int(r.status_code),
                    "final_url": r.url,
                    "content_type": r.headers.get("content-type"),
                    "content_length": r.headers.get("content-length"),
                    "accept_ranges": r.headers.get("accept-ranges"),
                }
        except requests.RequestException:
            pass

        r = self.session.get(
            url,
            headers={"Range": "bytes=0-0"},
            timeout=self.timeout,
            allow_redirects=True,
            stream=True,
        )
        try:
            ok = r.status_code in (200, 206)
            return {
                "ok": bool(ok),
                "method": "GET_RANGE_0_0",
                "status_code": int(r.status_code),
                "final_url": r.url,
                "content_type": r.headers.get("content-type"),
                "content_length": r.headers.get("content-length"),
                "content_range": r.headers.get("content-range"),
                "accept_ranges": r.headers.get("accept-ranges"),
            }
        finally:
            r.close()


def parse_wcs_capabilities(xml_bytes: bytes) -> dict[str, Any]:
    root = ET.fromstring(xml_bytes)
    coverage_ids = []
    formats = []
    crs_values = []
    versions = []
    for el in root.iter():
        name = localname(el.tag)
        text = (el.text or "").strip()
        if name in {"CoverageId", "Identifier"} and text:
            coverage_ids.append(text)
        if name in {"formatSupported", "FormatSupported"} and text:
            formats.append(text)
        if name in {"crsSupported", "CrsSupported"} and text:
            crs_values.append(text)
        if name in {"ServiceTypeVersion"} and text:
            versions.append(text)
    return {
        "root_tag": localname(root.tag),
        "coverage_ids": sorted(set(coverage_ids)),
        "formats": sorted(set(formats)),
        "crs": sorted(set(crs_values)),
        "versions": sorted(set(versions)),
    }


def parse_wfs_capabilities(xml_bytes: bytes) -> dict[str, Any]:
    root = ET.fromstring(xml_bytes)
    feature_types = []
    crs_values = []
    version = root.attrib.get("version")
    for ft in root.iter():
        if localname(ft.tag) != "FeatureType":
            continue
        item: dict[str, Any] = {}
        for child in ft.iter():
            name = localname(child.tag)
            text = (child.text or "").strip()
            if name == "Name" and text and "name" not in item:
                item["name"] = text
            elif name in {"Title"} and text and "title" not in item:
                item["title"] = text
            elif name in {"DefaultCRS", "DefaultSRS"} and text:
                item["default_crs"] = text
                crs_values.append(text)
        if item:
            feature_types.append(item)
    return {
        "root_tag": localname(root.tag),
        "version": version,
        "feature_types": feature_types,
        "crs": sorted(set(crs_values)),
    }


def get_properties_from_feature_collection(document: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    features = document.get("features") or []
    if not features:
        return {}, document.get("numberMatched")
    return dict(features[0].get("properties") or {}), document.get("numberMatched")


def parse_json_schema_properties(document: dict[str, Any]) -> list[str]:
    props = document.get("properties") or {}
    return sorted(str(k) for k in props.keys())


def html_contains_all(text: str, terms: list[str]) -> tuple[bool, list[str]]:
    normalized = re.sub(r"\s+", " ", text)
    missing = [term for term in terms if term.lower() not in normalized.lower()]
    return (not missing), missing


def probe_sgu_smallmag(p: Probe, cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg["sources"]["sgu_smallmag"]
    bulk = p.head_or_range(s["bulk_zip"])
    wcs = p.get(s["wcs_capabilities"], max_bytes=3_000_000)
    parsed = parse_wcs_capabilities(wcs.content)
    ok = bool(bulk["ok"] and parsed["coverage_ids"])
    return {
        "status": "PASS" if ok else "FAIL",
        "product_page": s["product_page"],
        "bulk_probe": bulk,
        "wcs_url": wcs.url,
        "wcs_status_code": wcs.status_code,
        "wcs_content_type": wcs.headers.get("content-type"),
        "wcs": parsed,
        "semantics": {
            "unit": "l/day/ha according to SGU product documentation",
            "cell_size_m": 100,
            "use": "regional/local screening; not individual well-yield determination",
        },
    }


def probe_sgu_magazines(p: Probe, cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg["sources"]["sgu_groundwater_magazines"]
    landing = p.get(s["ogc_landing"], max_bytes=1_000_000)
    collections = p.get(s["ogc_collections"], max_bytes=2_000_000).json()
    ids = sorted(str(c.get("id")) for c in collections.get("collections", []) if c.get("id"))
    return {
        "status": "PASS" if ids else "FAIL",
        "landing_status_code": landing.status_code,
        "landing_url": landing.url,
        "collections": ids,
        "license_links": [
            link.get("href") for link in collections.get("links", [])
            if link.get("rel") == "license"
        ],
    }


def probe_sgu_hype(p: Probe, cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg["sources"]["sgu_hype"]
    exp = cfg["expected"]

    collections_doc = p.get(s["collections"], max_bytes=3_000_000).json()
    collections = {
        str(c.get("id")): c for c in collections_doc.get("collections", []) if c.get("id")
    }
    collection_ids = sorted(collections)

    area_q = p.get(s["areas_queryables"], max_bytes=1_000_000).json()
    hist_q = p.get(s["history_queryables"], max_bytes=1_000_000).json()
    area_fields = parse_json_schema_properties(area_q)
    history_fields = parse_json_schema_properties(hist_q)

    area_doc = p.get(s["areas_sample"], max_bytes=2_000_000).json()
    area_props, number_matched = get_properties_from_feature_collection(area_doc)
    area_id = area_props.get("omrade_id")
    url_ts = area_props.get("url_tidsserie")

    sample_history: dict[str, Any] = {}
    if area_id is not None:
        hist_r = p.get(
            s["history_items_base"],
            params={
                "f": "application/geo+json",
                "filter": f"omrade_id={area_id}",
                "limit": 5,
            },
            max_bytes=2_000_000,
        )
        hist_doc = hist_r.json()
        hist_props, hist_matched = get_properties_from_feature_collection(hist_doc)
        sample_history = {
            "request_url": hist_r.url,
            "number_matched": hist_matched,
            "sample_properties": hist_props,
            "sample_property_names": sorted(hist_props),
        }

    missing_collections = sorted(set(exp["sgu_hype_collections"]) - set(collection_ids))
    missing_area_fields = sorted(set(exp["sgu_hype_area_fields"]) - set(area_fields))
    missing_history_fields = sorted(set(exp["sgu_hype_history_fields"]) - set(history_fields))

    license_links = [
        link.get("href") for link in collections_doc.get("links", [])
        if link.get("rel") == "license"
    ]

    area_collection = collections.get("omraden", {})
    ok = (
        not missing_collections
        and not missing_area_fields
        and not missing_history_fields
        and area_id is not None
        and isinstance(url_ts, str)
        and bool(sample_history.get("sample_properties"))
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "collections": collection_ids,
        "missing_expected_collections": missing_collections,
        "license_links": license_links,
        "service_crs": collections_doc.get("crs"),
        "area_collection_crs": area_collection.get("crs"),
        "area_collection_storage_crs": area_collection.get("storageCrs"),
        "area_queryable_fields": area_fields,
        "history_queryable_fields": history_fields,
        "missing_expected_area_fields": missing_area_fields,
        "missing_expected_history_fields": missing_history_fields,
        "sample_area": {
            "number_matched": number_matched,
            "properties": area_props,
            "omrade_id": area_id,
            "url_tidsserie": url_ts,
        },
        "sample_history": sample_history,
        "semantics": {
            "grid_description": "approximately 4x4 km SGU-HYPE areas according to SGU",
            "historical_series": "daily modelled relative groundwater-state/filling variables; period can vary by area and must be measured per cell",
        },
    }


def probe_smhi_svar2022(p: Probe, cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg["sources"]["smhi_svar2022"]
    page = p.get(s["explorer_page"], max_bytes=2_000_000)
    bulk = p.head_or_range(s["bulk_zip"])
    wfs = p.get(s["wfs_capabilities"], max_bytes=4_000_000)
    parsed = parse_wfs_capabilities(wfs.content)
    page_text = page.text
    mentions_2022 = "SVAR2022" in page_text or "SVAR 2022" in page_text
    ok = bool(bulk["ok"] and parsed["feature_types"] and mentions_2022)
    return {
        "status": "PASS" if ok else "FAIL",
        "explorer_page_status_code": page.status_code,
        "mentions_svar2022": mentions_2022,
        "bulk_probe": bulk,
        "wfs_url": wfs.url,
        "wfs_status_code": wfs.status_code,
        "wfs_content_type": wfs.headers.get("content-type"),
        "wfs": parsed,
        "mapping_note": (
            "This public SVAR2022 geometry product must not be assumed to expose the same SUBID/AROID identifiers "
            "used by current S-HYPE/NADIA until the B pilot proves the mapping."
        ),
    }


def probe_smhi_shype(p: Probe, cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg["sources"]["smhi_shype"]
    terms = cfg["expected"]["smhi_nadia_terms"]

    overview = p.get(s["overview"], max_bytes=2_000_000)
    docs = p.get(s["model_area_docs"], max_bytes=2_000_000)
    nadia = p.get(s["nadia_bulk"], max_bytes=3_000_000)
    modelarea = p.get(s["modelarea"], max_bytes=3_000_000)

    nadia_ok, nadia_missing = html_contains_all(nadia.text, terms)
    docs_ok = all(
        t.lower() in docs.text.lower()
        for t in ("SUBID", "S-HYPE", "vattenflöde")
    )
    modelarea_ok = "S-HYPE" in modelarea.text and (
        "SUBID" in modelarea.text or "AROID" in modelarea.text
    )

    return {
        "status": "PASS" if (nadia_ok and docs_ok and modelarea_ok) else "FAIL",
        "overview_status_code": overview.status_code,
        "docs_status_code": docs.status_code,
        "nadia_status_code": nadia.status_code,
        "nadia_final_url": nadia.url,
        "nadia_expected_terms_missing": nadia_missing,
        "modelarea_status_code": modelarea.status_code,
        "documented_bulk_mechanism": {
            "type": "official interactive multi-area bulk download",
            "identifiers": ["SUBID", "AROID"],
            "time_step": "daily available in documented interface",
            "documented_variables": [
                "local flow",
                "total flow",
                "station-corrected total flow",
                "natural flow",
                "stream temperature",
            ],
            "documented_historical_availability_note": "SMHI Vattenwebb states flow data from 1991 are available in multi-download.",
            "programmatic_backend_endpoint_documented": False,
        },
        "identifier_geometry_mapping_status": "OPEN_FOR_STOPPUNKT_B",
        "identifier_geometry_mapping_note": (
            "Official Vattenwebb accepts SUBID/AROID and official SVAR2022 geometry is reachable, "
            "but A2 does not assume those public geometry attributes directly equal the current S-HYPE identifiers. "
            "Prove linkage on the deterministic 100-field pilot before scaling."
        ),
    }


def probe_licenses(p: Probe, cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg["sources"]["licenses"]
    sgu = p.get(s["sgu"], max_bytes=2_000_000)
    smhi = p.get(s["smhi"], max_bytes=2_000_000)

    sgu_text = re.sub(r"\s+", " ", sgu.text).lower()
    smhi_text = re.sub(r"\s+", " ", smhi.text).lower()

    sgu_cc0 = ("cc0" in sgu_text) or ("creative commons noll" in sgu_text)
    smhi_ccby = (
        "erkännande 4.0" in smhi_text
        or "cc by 4.0" in smhi_text
        or "creative commons" in smhi_text and "4.0" in smhi_text
    )
    return {
        "status": "PASS" if (sgu_cc0 and smhi_ccby) else "FAIL",
        "sgu": {
            "url": sgu.url,
            "status_code": sgu.status_code,
            "detected_license": "CC0" if sgu_cc0 else "UNKNOWN",
        },
        "smhi": {
            "url": smhi.url,
            "status_code": smhi.status_code,
            "detected_license": "CC BY 4.0 / Creative Commons Erkännande 4.0" if smhi_ccby else "UNKNOWN",
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# ÅkerVatten MVP v0a · STOPPUNKT A2 official source inventory",
        "",
        f"**Overall status: {result['status']}**",
        "",
        "No large public source dataset was downloaded by this inventory.",
        "",
        "## SGU — Grundvattentillgång i små magasin",
        "",
    ]
    sm = result["sgu_smallmag"]
    lines += [
        f"- Status: **{sm['status']}**",
        f"- WCS coverages: {', '.join(sm['wcs']['coverage_ids']) or 'none detected'}",
        f"- WCS formats: {', '.join(sm['wcs']['formats']) or 'not reported'}",
        f"- Bulk route probe: {sm['bulk_probe']['status_code']} via {sm['bulk_probe']['method']}",
        "- Semantics: regional/local screening; not a field-specific well-yield claim.",
        "",
        "## SGU — Grundvattenmagasin",
        "",
    ]
    gm = result["sgu_groundwater_magazines"]
    lines += [
        f"- Status: **{gm['status']}**",
        f"- OGC collections: {', '.join(gm['collections']) or 'none'}",
        "",
        "## SGU-HYPE",
        "",
    ]
    gh = result["sgu_hype"]
    lines += [
        f"- Status: **{gh['status']}**",
        f"- Collections: {', '.join(gh['collections'])}",
        f"- Area storage CRS: {gh.get('area_collection_storage_crs')}",
        f"- Sample area ID: {gh['sample_area'].get('omrade_id')}",
        f"- Sample time-series URL present: {'yes' if gh['sample_area'].get('url_tidsserie') else 'no'}",
        f"- History fields: {', '.join(gh['history_queryable_fields'])}",
        "",
        "## SMHI — SVAR2022 geometry",
        "",
    ]
    sv = result["smhi_svar2022"]
    lines += [
        f"- Status: **{sv['status']}**",
        f"- WFS feature types: {', '.join(x.get('name','') for x in sv['wfs']['feature_types'])}",
        f"- WFS CRS: {', '.join(sv['wfs']['crs']) or 'not reported'}",
        f"- Bulk route probe: {sv['bulk_probe']['status_code']} via {sv['bulk_probe']['method']}",
        "",
        "## SMHI — S-HYPE / Vattenwebb / NADIA",
        "",
    ]
    sh = result["smhi_shype"]
    lines += [
        f"- Status: **{sh['status']}**",
        "- Documented bulk identifiers: SUBID / AROID.",
        "- Documented flow variables include local, total, station-corrected total and natural flow.",
        f"- Geometry ↔ current S-HYPE identifier mapping: **{sh['identifier_geometry_mapping_status']}**",
        f"- Note: {sh['identifier_geometry_mapping_note']}",
        "",
        "## Licenses",
        "",
        f"- SGU: {result['licenses']['sgu']['detected_license']}",
        f"- SMHI: {result['licenses']['smhi']['detected_license']}",
        "",
        "## A2 decision",
        "",
    ]
    if result["status"] == "PASS":
        lines += [
            "Official source routes, schemas and licenses are sufficiently inventoried to proceed to STOPPUNKT B.",
            "",
            "The 100-field pilot must explicitly prove the current S-HYPE geometry-to-SUBID/AROID linkage before any full-Skåne join.",
        ]
    else:
        lines += [
            "Do not proceed to STOPPUNKT B until the failed source probes are understood.",
        ]
    lines += ["", "## Guardrails", ""]
    for g in result["guardrails"]:
        lines.append("- " + g)
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    p = Probe(
        timeout=int(cfg["network"]["timeout_seconds"]),
        user_agent=str(cfg["network"]["user_agent"]),
    )

    result: dict[str, Any] = {
        "schema_version": "akervatten-mvp-v0a-a2-source-inventory-result",
        "run_epoch_utc": int(time.time()),
        "guardrails": cfg["guardrails"],
    }

    problems = []
    probes = [
        ("sgu_smallmag", probe_sgu_smallmag),
        ("sgu_groundwater_magazines", probe_sgu_magazines),
        ("sgu_hype", probe_sgu_hype),
        ("smhi_svar2022", probe_smhi_svar2022),
        ("smhi_shype", probe_smhi_shype),
        ("licenses", probe_licenses),
    ]

    print("=" * 116)
    print("ÅkerVatten MVP v0a · STOPPUNKT A2 OFFICIAL SOURCE INVENTORY")
    print("=" * 116)
    print("Network probes are deliberately small; no full public raster/vector/time-series download.\n")

    for name, fn in probes:
        print(f"[probe] {name} ...", flush=True)
        try:
            value = fn(p, cfg)
            result[name] = value
            print(f"        {value['status']}")
            if value["status"] != "PASS":
                problems.append(f"{name}: {value['status']}")
        except Exception as exc:
            result[name] = {"status": "ERROR", "error": repr(exc)}
            problems.append(f"{name}: {exc}")
            print(f"        ERROR: {exc}")

    result["problems"] = problems
    result["status"] = "PASS" if not problems else "FAIL"

    (work / "source_inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (work / "source_inventory.md").write_text(
        render_markdown(result),
        encoding="utf-8",
    )

    print("\nSUMMARY")
    for name, _ in probes:
        print(f"  {name:30s} {result[name]['status']}")

    gh = result.get("sgu_hype", {})
    if gh.get("status") == "PASS":
        print("\nSGU-HYPE")
        print("  collections:", ", ".join(gh.get("collections", [])))
        print("  storage CRS:", gh.get("area_collection_storage_crs"))
        print("  sample area ID:", gh.get("sample_area", {}).get("omrade_id"))
        print("  sample history fields:", ", ".join(gh.get("sample_history", {}).get("sample_property_names", [])))

    sv = result.get("smhi_svar2022", {})
    if sv.get("status") == "PASS":
        print("\nSMHI SVAR2022")
        print("  WFS feature types:", ", ".join(x.get("name","") for x in sv.get("wfs", {}).get("feature_types", [])))
        print("  CRS:", ", ".join(sv.get("wfs", {}).get("crs", [])))

    sh = result.get("smhi_shype", {})
    if sh.get("status") == "PASS":
        print("\nSMHI S-HYPE / NADIA")
        print("  documented identifiers: SUBID / AROID")
        print("  geometry linkage:", sh.get("identifier_geometry_mapping_status"))
        print("  NOTE:", sh.get("identifier_geometry_mapping_note"))

    lic = result.get("licenses", {})
    if lic.get("status") == "PASS":
        print("\nLICENSES")
        print("  SGU :", lic["sgu"]["detected_license"])
        print("  SMHI:", lic["smhi"]["detected_license"])

    if problems:
        print("\nPROBLEMS")
        for item in problems:
            print("  - " + item)

    print(f"\nOutputs: {work}")
    print("=" * 116)
    print(f"AKERVATTEN A2 OFFICIAL SOURCE INVENTORY: {result['status']}")
    print("=" * 116)
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
