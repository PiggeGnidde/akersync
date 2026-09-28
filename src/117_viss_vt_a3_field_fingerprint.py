"""ÅkerKontext · VattenTryck — VT-A3 field fingerprint model.

Builds a product-neutral, field-level VISS fingerprint for all 128,636 Skåne
fields from frozen VT-A2b relations and VT-A1 classifications.

Semantics are deliberately descriptive:
- pressure flags mean VISS Classification=Y for that groundwater body/type;
- quantitative_risk_signal means a non-empty/non-'Ej klassad' VISS quantitative
  risk classification;
- no composite score is invented;
- absence of a flag is NOT interpreted as absence of water use or legal right;
- all overlapping EU_CD relations are retained, while dominant_EU_CD is only a
  UI convenience inherited from VT-A2b.

No network access and no web/UI modification.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
A1C = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a1c"
A2 = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a2"
A2B = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a2b"
OUT = ROOT / "data" / "derived" / "akervatten" / "viss_vt_a3"
EXPECTED_FIELDS = 128_636


def load_json(path: Path):
    if not path.exists():
        raise RuntimeError(f"Missing {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm(x):
    return "" if x is None else str(x).strip().upper()


def clean_text(x):
    return " ".join(str(x or "").split())


def pressure_category(label: str):
    low = label.lower()
    if "uttag" not in low:
        return None
    if "jordbruk" in low:
        return "agriculture"
    if "kommunal" in low or "allmän" in low:
        return "municipal"
    if "tillverkningsindustri" in low:
        return "industry"
    if label.strip() == "3 Vattenuttag":
        return "generic"
    return "other"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 88)
    print("ÅkerKontext · VattenTryck — VT-A3 field fingerprint")
    print("=" * 88)

    a2 = load_json(A2 / "summary.json")
    waters = load_json(A1C / "waters.json")
    pressures = load_json(A1C / "measuregroundwaterpressuremotivations.json")
    risks = load_json(A1C / "waterriskclassifications.json")

    field_source = Path(a2["field_source"])
    if not field_source.exists():
        raise RuntimeError(f"Field source missing: {field_source}")

    # Read only attributes needed for the canonical field universe.
    import geopandas as gpd
    fields = gpd.read_file(field_source, ignore_geometry=True)
    for col in ("blockid", "skiftesbeteckning"):
        if col not in fields.columns:
            raise RuntimeError(f"Field source missing {col}")
    fields["field_id"] = fields["blockid"].astype(str) + "|" + fields["skiftesbeteckning"].astype(str)
    if len(fields) != EXPECTED_FIELDS or fields["field_id"].nunique() != EXPECTED_FIELDS:
        raise RuntimeError(f"Expected {EXPECTED_FIELDS:,} unique fields; got rows={len(fields):,}, unique={fields['field_id'].nunique():,}")
    base = fields[["field_id", "blockid", "skiftesbeteckning"]].copy()

    rel_path = A2B / "field_case_overlap_relations.parquet"
    dom_path = A2B / "field_dominant_case.parquet"
    if not rel_path.exists() or not dom_path.exists():
        raise RuntimeError("Missing VT-A2b relations; run src/116_viss_vt_a2b_robust_field_join.py")
    rel = pd.read_parquet(rel_path)
    dom = pd.read_parquet(dom_path)
    rel["EU_CD_N"] = rel["EU_CD_N"].map(norm)
    dom["dominant_EU_CD"] = dom["dominant_EU_CD"].map(norm)

    water_name = {norm(w.get("EU_CD")): str(w.get("Name") or w.get("EU_CD")) for w in waters}

    # Exact positive withdrawal evidence per water body.
    cats = defaultdict(set)
    motivations = defaultdict(list)
    for r in pressures:
        if str(r.get("Classification") or "").strip() != "Y":
            continue
        euid = norm(r.get("WaterEUID"))
        label = str(r.get("MeasureGroundWaterPressureType") or "").strip()
        cat = pressure_category(label)
        if not cat:
            continue
        cats[euid].add(cat)
        mot = clean_text(r.get("Motivation"))
        if mot:
            motivations[euid].append({"type": label, "motivation": mot, "date": str(r.get("Date") or "")})

    # Quantitative risk signal and its listed impacts.
    q_risk = {}
    for r in risks:
        if str(r.get("WaterCategory") or "") != "GW":
            continue
        euid = norm(r.get("EU_CD"))
        for sec in r.get("RiskSections") or []:
            if sec.get("SectionName") != "Kvantitativ status - Grundvatten":
                continue
            risk = str(sec.get("Risk") or "").strip()
            if risk in ("", "Ej klassad", "Ingen"):
                continue
            impacts = sorted({str(i.get("Impact") or "").strip() for i in (sec.get("Impacts") or []) if str(i.get("Impact") or "").strip()})
            q_risk[euid] = {"classification": risk, "impacts": impacts}

    # Relation-level evidence: scientifically useful long table.
    for cat in ("agriculture", "municipal", "industry", "generic", "other"):
        rel[f"pressure_{cat}"] = rel["EU_CD_N"].map(lambda x: cat in cats.get(x, set()))
    rel["quantitative_risk_signal"] = rel["EU_CD_N"].isin(q_risk)
    rel["water_name"] = rel["EU_CD_N"].map(water_name)
    rel["quantitative_risk_class"] = rel["EU_CD_N"].map(lambda x: q_risk.get(x, {}).get("classification", ""))
    rel["quantitative_risk_impacts"] = rel["EU_CD_N"].map(lambda x: "; ".join(q_risk.get(x, {}).get("impacts", [])))
    rel.to_parquet(OUT / "field_viss_relations.parquet", index=False)

    # Aggregate to one product-neutral fingerprint row per field.
    grouped = rel.groupby("field_id", sort=False)
    agg = grouped.agg(
        viss_gw_relation_count=("EU_CD_N", "nunique"),
        max_overlap_fraction=("overlap_fraction", "max"),
        any_rep_point_inside=("representative_point_inside", "max"),
        pressure_agriculture=("pressure_agriculture", "max"),
        pressure_municipal=("pressure_municipal", "max"),
        pressure_industry=("pressure_industry", "max"),
        pressure_generic=("pressure_generic", "max"),
        pressure_other=("pressure_other", "max"),
        quantitative_risk_signal=("quantitative_risk_signal", "max"),
    ).reset_index()
    ids = grouped["EU_CD_N"].agg(lambda x: ";".join(sorted(set(x)))).rename("viss_gw_eu_cd").reset_index()
    agg = agg.merge(ids, on="field_id", how="left")
    agg["viss_positive_case"] = True

    fp = base.merge(agg, on="field_id", how="left").merge(
        dom[["field_id", "dominant_EU_CD", "overlap_fraction"]].rename(columns={"overlap_fraction": "dominant_overlap_fraction"}),
        on="field_id", how="left"
    )
    bool_cols = ["viss_positive_case", "any_rep_point_inside", "pressure_agriculture", "pressure_municipal", "pressure_industry", "pressure_generic", "pressure_other", "quantitative_risk_signal"]
    for c in bool_cols:
        fp[c] = fp[c].fillna(False).astype(bool)
    fp["viss_gw_relation_count"] = fp["viss_gw_relation_count"].fillna(0).astype(int)
    fp["viss_gw_eu_cd"] = fp["viss_gw_eu_cd"].fillna("")
    fp["dominant_EU_CD"] = fp["dominant_EU_CD"].fillna("")
    fp["dominant_name"] = fp["dominant_EU_CD"].map(water_name).fillna("")

    if len(fp) != EXPECTED_FIELDS or fp["field_id"].nunique() != EXPECTED_FIELDS:
        raise RuntimeError("Fingerprint lost or duplicated fields")

    # Counts are not mutually exclusive because one field/body can have several pressures.
    print(f"Fields in fingerprint:                  {len(fp):,}")
    print(f"Any positive VISS case:                 {int(fp.viss_positive_case.sum()):,}")
    print(f"Agricultural withdrawal pressure:       {int(fp.pressure_agriculture.sum()):,}")
    print(f"Municipal/public withdrawal pressure:   {int(fp.pressure_municipal.sum()):,}")
    print(f"Industrial withdrawal pressure:         {int(fp.pressure_industry.sum()):,}")
    print(f"Generic withdrawal pressure:            {int(fp.pressure_generic.sum()):,}")
    print(f"Other withdrawal pressure:              {int(fp.pressure_other.sum()):,}")
    print(f"Quantitative risk signal:               {int(fp.quantitative_risk_signal.sum()):,}")
    print(f"Fields linked to >1 case EU_CD:          {int((fp.viss_gw_relation_count > 1).sum()):,}")

    fp.to_parquet(OUT / "field_viss_fingerprint.parquet", index=False)

    # Water-body evidence table carries motivation text separately; do not replicate
    # long prose 10,000 times into the field table.
    evidence = []
    all_euids = sorted(set(rel["EU_CD_N"]))
    for euid in all_euids:
        evidence.append({
            "EU_CD": euid,
            "name": water_name.get(euid, euid),
            "pressure_categories": sorted(cats.get(euid, set())),
            "withdrawal_motivations": motivations.get(euid, []),
            "quantitative_risk": q_risk.get(euid),
        })
    (OUT / "waterbody_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    semantics = {
        "version": "VT-A3-v0a",
        "field_count": EXPECTED_FIELDS,
        "rules": {
            "viss_positive_case": "Field has positive-area overlap with one of the frozen VT-A1 case groundwater bodies.",
            "pressure_*": "At least one overlapping case groundwater body has VISS Classification=Y for that withdrawal category.",
            "quantitative_risk_signal": "At least one overlapping case groundwater body has a VISS quantitative-status risk value other than blank/Ej klassad/Ingen.",
            "dominant_EU_CD": "Overlapping case groundwater body with maximum field overlap area; UI convenience only.",
            "absence": "False/blank means no such positive VISS signal in this dataset; it does NOT prove absence of water withdrawal, impact, permit, or legal right.",
            "score": "No composite VattenTryck score is defined in VT-A3.",
        },
        "recommended_ui_labels_sv": {
            "section": "VISS – vattenuttag och kvantitativ påverkan",
            "pressure_agriculture": "Signifikant påverkan från jordbruksuttag",
            "pressure_municipal": "Signifikant påverkan från kommunal/allmän vattentäkt",
            "pressure_industry": "Signifikant påverkan från tillverkningsindustri",
            "pressure_generic": "Signifikant påverkan från vattenuttag",
            "pressure_other": "Annan signifikant påverkan från vattenuttag",
            "quantitative_risk_signal": "Kvantitativ risksignal i VISS",
            "no_signal": "Ingen positiv VISS-signal i denna datamängd",
        },
        "warning_sv": "VISS-signaler beskriver myndighetsklassad påverkan/risk på grundvattenförekomsten. De anger inte uttagsvolym, tillståndsstatus eller juridisk rätt att ta vatten. Avsaknad av signal ska inte tolkas som att uttag saknas.",
    }
    (OUT / "semantics.json").write_text(json.dumps(semantics, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSaved: data/derived/akervatten/viss_vt_a3/")
    print("  field_viss_fingerprint.parquet")
    print("  field_viss_relations.parquet")
    print("  waterbody_evidence.json")
    print("  semantics.json")
    print("VT-A3 FIELD FINGERPRINT COMPLETE")
    print("=" * 88)


if __name__ == "__main__":
    main()
