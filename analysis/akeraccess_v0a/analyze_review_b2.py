#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze completed ÅkerAccess STOPPUNKT B2 visual QA."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK = ROOT / "work" / "akeraccess_v0a" / "sjobo"


def find_qa(work: Path, explicit: str | None) -> Path:
    if explicit:
        p=Path(explicit)
        if p.exists(): return p
        raise FileNotFoundError(p)
    name="sjobo_akeraccess_visual_qa_b2.csv"
    for p in [work/name, work/"review_b2"/name, Path.home()/"Downloads"/name, Path.home()/"Nedladdningar"/name]:
        if p.exists(): return p
    raise FileNotFoundError(name)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--qa",default=None)
    args=ap.parse_args()
    work=Path(args.work)
    qa=find_qa(work,args.qa)
    d=pd.read_csv(qa,encoding="utf-8-sig",low_memory=False)
    if len(d)!=80:
        raise RuntimeError(f"Expected 80 B2 rows, got {len(d)}")
    if d["final_label"].isna().any() or d["final_label"].astype(str).str.strip().eq("").any():
        raise RuntimeError("B2 QA contains unlabelled rows")

    d["candidate_plausible"]=d["final_label"].isin(["RANK1_PLAUSIBLE","OTHER_CANDIDATE_BETTER"])
    d["visible_access_any"]=d["final_label"].isin([
        "RANK1_PLAUSIBLE","OTHER_CANDIDATE_BETTER","ACCESS_VISIBLE_NOT_CANDIDATE"
    ])
    d["rank1_plausible"]=d["final_label"].eq("RANK1_PLAUSIBLE")
    d["excluded"]=d["final_label"].eq("EXCLUDE_OTHER")

    rows=[]
    for status,g in d.groupby("auto_status",sort=False):
        q=g[~g["excluded"]].copy()
        rows.append({
            "auto_status":status,
            "n":int(len(g)),
            "n_relevant":int(len(q)),
            "rank1_plausible":int(q["rank1_plausible"].sum()),
            "any_candidate_plausible":int(q["candidate_plausible"].sum()),
            "visible_access_not_candidate":int(q["final_label"].eq("ACCESS_VISIBLE_NOT_CANDIDATE").sum()),
            "no_visible_access":int(q["final_label"].eq("NO_VISIBLE_ACCESS").sum()),
            "unclear":int(q["final_label"].eq("UNCLEAR").sum()),
            "candidate_plausible_pct":float(100*q["candidate_plausible"].mean()) if len(q) else None,
            "visible_access_any_pct":float(100*q["visible_access_any"].mean()) if len(q) else None,
        })
    by_status=pd.DataFrame(rows)

    candidate_statuses={"STRONG_OSM_EVIDENCE","POSSIBLE_OSM_EVIDENCE","ADJACENCY_ONLY"}
    cand=d[d["auto_status"].isin(candidate_statuses)&~d["excluded"]].copy()
    noosm=d[d["auto_status"].eq("NO_OSM_ENTRY_EVIDENCE")&~d["excluded"]].copy()
    new=d[d["label_source"].eq("human_b2")&~d["excluded"]].copy()

    report={
        "schema_version":"akeraccess-b2-result-v0c",
        "qa_source":str(qa),
        "rows":int(len(d)),
        "candidate_bearing_relevant_rows":int(len(cand)),
        "candidate_plausible_rows":int(cand["candidate_plausible"].sum()),
        "candidate_plausible_pct":float(100*cand["candidate_plausible"].mean()),
        "rank1_plausible_pct_candidate_bearing":float(100*cand["rank1_plausible"].mean()),
        "visible_access_any_pct_candidate_bearing":float(100*cand["visible_access_any"].mean()),
        "no_osm_rows":int(len(noosm)),
        "no_osm_visible_access_not_candidate":int(noosm["final_label"].eq("ACCESS_VISIBLE_NOT_CANDIDATE").sum()),
        "no_osm_no_visible_access":int(noosm["final_label"].eq("NO_VISIBLE_ACCESS").sum()),
        "no_osm_unclear":int(noosm["final_label"].eq("UNCLEAR").sum()),
        "fresh_human_b2_rows":int(len(new)),
        "policy_note":(
            "NO_OSM and disconnected local components should be HOLD/MANUAL CHECK for proactive crop-sourcing, "
            "not interpreted as proven physical inaccessibility."
        ),
    }

    out=work/"review_b2"
    by_path=out/"sjobo_review_b2_by_status.csv"
    report_path=out/"sjobo_review_b2_result.json"
    by_status.to_csv(by_path,index=False,encoding="utf-8-sig")
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print("="*96)
    print("ÅkerAccess STOPPUNKT B2 - RESULT")
    print("="*96)
    print(by_status.to_string(index=False,formatters={
        "candidate_plausible_pct":lambda x:f"{x:.1f}%",
        "visible_access_any_pct":lambda x:f"{x:.1f}%",
    }))
    print()
    print(f"Candidate-bearing classes: plausible OSM candidate in {report['candidate_plausible_rows']}/{report['candidate_bearing_relevant_rows']} = {report['candidate_plausible_pct']:.1f}%")
    print(f"NO OSM: visible missed access={report['no_osm_visible_access_not_candidate']}, no visible={report['no_osm_no_visible_access']}, unclear={report['no_osm_unclear']}")
    print(f"Fresh B2 human rows: {report['fresh_human_b2_rows']}")
    print(f"Report: {report_path}")
    print("="*96)
    print("STOPPUNKT B2 RESULT: PASS")
    print("="*96)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
