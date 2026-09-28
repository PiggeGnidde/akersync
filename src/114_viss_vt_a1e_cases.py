"""ÅkerKontext · VattenTryck — VT-A1e inspect positive VISS GW cases.

Consumes raw VISS JSON from VT-A1c. Prints and exports the actual groundwater
water bodies with positive/significant withdrawal pressure (Classification Y)
and/or quantitative-status potential impact, including VISS motivation text.
No score, no legal inference, no field join.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_DIR = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1c"
OUT_DIR = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1e"


def load(name):
    p = IN_DIR / name
    if not p.exists():
        raise RuntimeError(f"Missing {p}. Run src/112_viss_vt_a1c_inventory.py first.")
    return json.loads(p.read_text(encoding="utf-8"))


def s(x):
    return "" if x is None else str(x).strip()


def municipalities(row):
    vals = row.get("Municipalities") or []
    if vals and isinstance(vals[0], dict):
        return ", ".join(v.get("Name", v.get("Code", "")) for v in vals)
    return ", ".join(map(str, vals))


def compact(text, limit=420):
    text = " ".join(s(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    waters = load("waters.json")
    pressure_rows = load("measuregroundwaterpressuremotivations.json")
    risks = load("waterriskclassifications.json")

    water_by_id = {s(w.get("EU_CD")): w for w in waters}
    gw_ids = set(water_by_id)

    positive_withdrawals = []
    for r in pressure_rows:
        euid = s(r.get("WaterEUID"))
        ptype = s(r.get("MeasureGroundWaterPressureType"))
        if euid in gw_ids and "uttag" in ptype.lower() and s(r.get("Classification")) == "Y":
            positive_withdrawals.append(r)

    quantitative_risk = []
    for r in risks:
        euid = s(r.get("EU_CD"))
        if euid not in gw_ids or s(r.get("WaterCategory")) != "GW":
            continue
        for sec in r.get("RiskSections") or []:
            if s(sec.get("SectionName")) == "Kvantitativ status - Grundvatten" and s(sec.get("Risk")) not in ("", "Ej klassad", "Ingen"):
                quantitative_risk.append({"water": r, "section": sec})

    pos_by_water = defaultdict(list)
    for r in positive_withdrawals:
        pos_by_water[s(r.get("WaterEUID"))].append(r)
    risk_by_water = {s(x["water"].get("EU_CD")): x for x in quantitative_risk}
    case_ids = sorted(set(pos_by_water) | set(risk_by_water))

    print("=" * 88)
    print("ÅkerKontext · VattenTryck — VT-A1e positive VISS groundwater cases")
    print("=" * 88)
    print(f"Positive withdrawal rows (Y): {len(positive_withdrawals)}")
    print(f"Unique GW bodies with withdrawal Y: {len(pos_by_water)}")
    print(f"GW bodies with quantitative non-empty risk signal: {len(risk_by_water)}")
    print(f"Union of case water bodies: {len(case_ids)}")

    export_rows = []
    for euid in case_ids:
        w = water_by_id.get(euid, {})
        print("\n" + "-" * 88)
        print(f"{s(w.get('Name')) or euid} | {euid} | MS_CD={s(w.get('MS_CD'))}")
        print(f"Municipality codes: {', '.join(map(str, w.get('Municipalites') or []))}")
        print(f"Area km2: {w.get('SurfaceAreaKM2')}")

        prs = pos_by_water.get(euid, [])
        if prs:
            print("WITHDRAWAL PRESSURES:")
            for p in prs:
                ptype = s(p.get("MeasureGroundWaterPressureType"))
                date = s(p.get("Date"))
                mot = compact(p.get("Motivation"))
                print(f"  * {ptype} | class=Y | date={date}")
                print(f"    Motivation: {mot}")
                export_rows.append({
                    "EU_CD": euid,
                    "MS_CD": s(w.get("MS_CD")),
                    "Name": s(w.get("Name")),
                    "MunicipalityCodes": ";".join(map(str, w.get("Municipalites") or [])),
                    "SurfaceAreaKM2": w.get("SurfaceAreaKM2"),
                    "SignalKind": "withdrawal_pressure",
                    "Signal": ptype,
                    "Classification": "Y",
                    "Date": date,
                    "Motivation": " ".join(s(p.get("Motivation")).split()),
                })
        else:
            print("WITHDRAWAL PRESSURES: none with class Y")

        qr = risk_by_water.get(euid)
        if qr:
            sec = qr["section"]
            risk = s(sec.get("Risk"))
            impacts = "; ".join(sorted({s(i.get("Impact")) for i in (sec.get("Impacts") or []) if s(i.get("Impact"))}))
            print(f"QUANTITATIVE RISK: {risk}")
            print(f"  Impacts: {impacts or '<none listed>'}")
            export_rows.append({
                "EU_CD": euid,
                "MS_CD": s(w.get("MS_CD")),
                "Name": s(w.get("Name")),
                "MunicipalityCodes": ";".join(map(str, w.get("Municipalites") or [])),
                "SurfaceAreaKM2": w.get("SurfaceAreaKM2"),
                "SignalKind": "quantitative_risk",
                "Signal": impacts,
                "Classification": risk,
                "Date": "",
                "Motivation": "",
            })
        else:
            print("QUANTITATIVE RISK: none")

    csv_path = OUT_DIR / "positive_gw_cases.csv"
    fields = ["EU_CD", "MS_CD", "Name", "MunicipalityCodes", "SurfaceAreaKM2", "SignalKind", "Signal", "Classification", "Date", "Motivation"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(export_rows)

    summary = {
        "positive_withdrawal_rows": len(positive_withdrawals),
        "unique_positive_withdrawal_water_bodies": len(pos_by_water),
        "quantitative_risk_water_bodies": len(risk_by_water),
        "union_case_water_bodies": len(case_ids),
        "case_ids": case_ids,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 88)
    print(f"Saved: {csv_path.relative_to(ROOT)}")
    print(f"Saved: {(OUT_DIR / 'summary.json').relative_to(ROOT)}")
    print("VT-A1e CASE INSPECTION COMPLETE")
    print("=" * 88)


if __name__ == "__main__":
    main()
