"""ÅkerKontext · VattenTryck — VT-A1d VISS groundwater census.

Consumes raw JSON produced by 112_viss_vt_a1c_inventory.py and summarizes
Skåne groundwater pressure motivations, impacts and quantitative risk.
No score, no legal inference, no field join.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_DIR = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1c"
OUT_DIR = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1d"


def load(name):
    p = IN_DIR / name
    if not p.exists():
        raise RuntimeError(f"Missing {p}. Run src/112_viss_vt_a1c_inventory.py first.")
    return json.loads(p.read_text(encoding="utf-8"))


def norm(x):
    return "" if x is None else str(x).strip()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    waters = load("waters.json")
    pressures = load("measuregroundwaterpressuremotivations.json")
    impacts = load("measuregroundwaterimpactmotivations.json")
    risks = load("waterriskclassifications.json")

    gw_ids = {norm(w.get("EU_CD")) for w in waters}
    pressures = [r for r in pressures if norm(r.get("WaterEUID")) in gw_ids]
    impacts = [r for r in impacts if norm(r.get("WaterEUID")) in gw_ids]
    risks = [r for r in risks if norm(r.get("EU_CD")) in gw_ids and norm(r.get("WaterCategory")) == "GW"]

    print("=" * 78)
    print("ÅkerKontext · VattenTryck — VT-A1d VISS groundwater census")
    print("=" * 78)
    print(f"GW water bodies from waters: {len(gw_ids)}")
    print(f"Pressure motivation rows:    {len(pressures)}")
    print(f"Impact motivation rows:      {len(impacts)}")
    print(f"GW risk rows:                {len(risks)}")

    # Pressure census by exact VISS pressure type and classification.
    by_type = defaultdict(Counter)
    bodies_by_type_class = defaultdict(set)
    for r in pressures:
        ptype = norm(r.get("MeasureGroundWaterPressureType")) or "<blank>"
        cls = norm(r.get("Classification")) or "<blank>"
        by_type[ptype][cls] += 1
        bodies_by_type_class[(ptype, cls)].add(norm(r.get("WaterEUID")))

    print("\nPRESSURE TYPES / CLASSIFICATIONS")
    print("-" * 78)
    for ptype in sorted(by_type):
        classes = ", ".join(f"{k}={v}" for k, v in sorted(by_type[ptype].items()))
        print(f"{ptype}: {classes}")

    # Highlight anything whose label mentions withdrawal/abstraction in Swedish.
    withdrawal_types = [p for p in by_type if any(s in p.lower() for s in ("uttag", "vattenuttag"))]
    print("\nWITHDRAWAL-RELATED PRESSURE TYPES")
    print("-" * 78)
    if not withdrawal_types:
        print("No pressure type label containing 'uttag' found.")
    for ptype in sorted(withdrawal_types):
        print(ptype)
        for cls, nrows in sorted(by_type[ptype].items()):
            nbodies = len(bodies_by_type_class[(ptype, cls)])
            print(f"  classification={cls!r}: rows={nrows}, unique_water_bodies={nbodies}")

    print("\nIMPACTS")
    print("-" * 78)
    impact_counter = Counter((norm(r.get("MeasureGroundWaterImpactType")), norm(r.get("Classification"))) for r in impacts)
    for (itype, cls), n in sorted(impact_counter.items()):
        print(f"{itype} | classification={cls!r}: {n}")

    # RiskSections are nested. Print all GW section/risk/impact combinations so we
    # can see the actual vocabulary before freezing a quantitative-risk rule.
    section_counter = Counter()
    impact_risk_counter = Counter()
    risk_rows = []
    for r in risks:
        euid = norm(r.get("EU_CD"))
        for sec in r.get("RiskSections") or []:
            sname = norm(sec.get("SectionName"))
            risk = norm(sec.get("Risk"))
            section_counter[(sname, risk)] += 1
            risk_rows.append((euid, sname, risk))
            for imp in sec.get("Impacts") or []:
                impact_risk_counter[(sname, norm(imp.get("Impact")), norm(imp.get("Risk")))] += 1

    print("\nRISK SECTIONS")
    print("-" * 78)
    for (sname, risk), n in sorted(section_counter.items()):
        print(f"{sname} | {risk}: {n}")

    print("\nRISK IMPACTS")
    print("-" * 78)
    for (sname, imp, risk), n in sorted(impact_risk_counter.items()):
        print(f"{sname} | {imp} | {risk}: {n}")

    # Machine-readable census CSV.
    csv_path = OUT_DIR / "pressure_census.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["pressure_type", "classification", "rows", "unique_water_bodies"])
        for ptype in sorted(by_type):
            for cls, nrows in sorted(by_type[ptype].items()):
                w.writerow([ptype, cls, nrows, len(bodies_by_type_class[(ptype, cls)])])

    summary = {
        "gw_water_bodies": len(gw_ids),
        "pressure_rows": len(pressures),
        "impact_rows": len(impacts),
        "gw_risk_rows": len(risks),
        "withdrawal_pressure_types": sorted(withdrawal_types),
        "pressure_types": {p: dict(c) for p, c in sorted(by_type.items())},
        "risk_sections": [{"section": s, "risk": r, "count": n} for (s, r), n in sorted(section_counter.items())],
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"Saved: {csv_path.relative_to(ROOT)}")
    print(f"Saved: {(OUT_DIR / 'summary.json').relative_to(ROOT)}")
    print("VT-A1d CENSUS COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
