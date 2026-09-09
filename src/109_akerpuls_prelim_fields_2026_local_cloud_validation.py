#!/usr/bin/env python3
"""Low-PU local clear-sky validation of rescue dates for ÅkerPuls 2026."""
from __future__ import annotations
import argparse, csv, json, math, os, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_v0.json"
STATS_URL="https://sh.dataspace.copernicus.eu/statistics/v1"
SEARCH_WINDOWS={
    "S2_2026_APRIL":("2026-04-01","2026-04-16"),
    "S2_2026_JUNE":("2026-06-19","2026-07-04"),
}

def oauth(cfg):
    cid=os.getenv("CDSE_CLIENT_ID","").strip(); sec=os.getenv("CDSE_CLIENT_SECRET","").strip()
    if not cid or not sec:
        raise RuntimeError("BLOCKED_CREDENTIALS: CDSE_CLIENT_ID/CDSE_CLIENT_SECRET are not set")
    body=urllib.parse.urlencode({"grant_type":"client_credentials","client_id":cid,"client_secret":sec}).encode()
    req=urllib.request.Request(cfg["sentinel2"]["token_url"],data=body,method="POST",headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]

def evalscript():
    return """//VERSION=3
function setup(){
  return {
    input:[{bands:["SCL","CLD","dataMask"]}],
    output:[
      {id:"default",bands:["CLEAR","CLD"],sampleType:"FLOAT32"},
      {id:"dataMask",bands:1}
    ]
  };
}
function evaluatePixel(s){
  let clear=[2,4,5].indexOf(s.SCL)>=0 ? 1.0 : 0.0;
  return {default:[clear,s.CLD],dataMask:[s.dataMask?1:0]};
}"""

def geom_mapping(g):
    return json.loads(json.dumps(g.__geo_interface__))

def request_payload(g,start,end_exclusive):
    return {
      "input":{"bounds":{"geometry":geom_mapping(g),"properties":{"crs":"http://www.opengis.net/def/crs/EPSG/0/32633"}},
               "data":[{"type":"sentinel-2-l2a","dataFilter":{"timeRange":{"from":start+"T00:00:00Z","to":end_exclusive+"T00:00:00Z"},"maxCloudCoverage":100}}]},
      "aggregation":{"timeRange":{"from":start+"T00:00:00Z","to":end_exclusive+"T00:00:00Z"},
                     "aggregationInterval":{"of":"P1D","lastIntervalBehavior":"SKIP"},
                     "resx":20,"resy":20,"evalscript":evalscript()},
      "calculations":{"default":{"statistics":{"default":{}}}}
    }

def post_stats(token,payload):
    raw=json.dumps(payload,separators=(",",":")).encode("utf-8")
    req=urllib.request.Request(STATS_URL,data=raw,method="POST",headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=180) as r:
        body=json.loads(r.read().decode("utf-8"))
        pu=r.headers.get("x-processingunits-spent")
    return body, (float(pu) if pu not in (None,"") else 0.0)

def parse_daily(body,field_key):
    rows=[]
    for item in body.get("data",[]):
        iv=item.get("interval") or {}
        out=(item.get("outputs") or {}).get("default") or {}
        bands=out.get("bands") or {}
        cs=((bands.get("CLEAR") or {}).get("stats") or {})
        ds=((bands.get("CLD") or {}).get("stats") or {})
        n=int(cs.get("sampleCount") or 0); nd=int(cs.get("noDataCount") or 0)
        valid=max(0,n-nd)
        rows.append({
          "field_key":field_key,
          "date":str(iv.get("from") or "")[:10],
          "sample_pixels":n,
          "valid_pixels":valid,
          "clear_fraction":cs.get("mean"),
          "mean_cld":ds.get("mean"),
        })
    return rows

def quantile(v,q):
    x=sorted(v)
    if not x:return None
    p=(len(x)-1)*q; lo=int(math.floor(p)); hi=int(math.ceil(p))
    return x[lo] if lo==hi else x[lo]+(x[hi]-x[lo])*(p-lo)

def main():
    import geopandas as gpd
    import pandas as pd

    ap=argparse.ArgumentParser()
    ap.add_argument("--coverage-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_coverage_diag")
    ap.add_argument("--rescue-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_rescue_dates")
    ap.add_argument("--output-dir",default=r"C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_local_cloud")
    ap.add_argument("--samples-per-snapshot",type=int,default=12)
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    rank=pd.read_csv(Path(args.rescue_dir)/"rescue_date_ranking.csv")
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    token=oauth(cfg); all_daily=[]; sample_rows=[]; total_pu=0.0

    for snap in ("S2_2026_APRIL","S2_2026_JUNE"):
        gpkg=Path(args.coverage_dir)/f"{snap.lower()}_gap_fields.gpkg"
        g=gpd.read_file(gpkg).to_crs(32633)
        if "uncovered_fraction" not in g.columns:
            raise RuntimeError(f"{gpkg} lacks uncovered_fraction")
        full=g[g["uncovered_fraction"]>=0.999].copy()
        if len(full)<args.samples_per_snapshot:
            full=g[g["uncovered_fraction"]>=0.90].copy()
        full["cy"]=full.geometry.centroid.y
        full["area_m2"]=full.geometry.area
        full=full.sort_values(["cy","area_m2"]).reset_index(drop=True)
        n=min(args.samples_per_snapshot,len(full))
        idx=sorted(set(round(i*(len(full)-1)/(n-1)) for i in range(n))) if n>1 else [len(full)//2]
        sel=full.iloc[idx].copy().reset_index(drop=True)
        for j,row in sel.iterrows():
            key=f"{snap}_{j+1:02d}"
            sample_rows.append({"snapshot":snap,"field_key":key,"uncovered_fraction":float(row["uncovered_fraction"]),"area_ha":float(row.geometry.area/10000.0),"centroid_y":float(row.geometry.centroid.y)})
            a,b=SEARCH_WINDOWS[snap]
            end=(date.fromisoformat(b)+timedelta(days=1)).isoformat()
            body,pu=post_stats(token,request_payload(row.geometry,a,end))
            total_pu += pu
            all_daily.extend(parse_daily(body,key))

    daily=pd.DataFrame(all_daily)
    daily.to_csv(out/"local_cloud_daily_samples.csv",index=False)
    pd.DataFrame(sample_rows).to_csv(out/"sample_fields.csv",index=False)

    result=[]
    for snap in ("S2_2026_APRIL","S2_2026_JUNE"):
        frozen=[date.fromisoformat(d) for d in cfg["snapshots"][snap]]
        candidates=rank[(rank["snapshot"]==snap)&(rank["gap_rescue_percent"]>=90.0)].copy()
        for r in candidates.itertuples(index=False):
            d=str(r.candidate_date)
            sub=daily[(daily["date"]==d)&(daily["field_key"].str.startswith(snap))].copy()
            vals=pd.to_numeric(sub["clear_fraction"],errors="coerce").dropna().tolist()
            cld=pd.to_numeric(sub["mean_cld"],errors="coerce").dropna().tolist()
            if not vals:
                continue
            dist=min(abs((date.fromisoformat(d)-fd).days) for fd in frozen)
            med=float(pd.Series(vals).median())
            p10=float(quantile(vals,0.10))
            clear70=sum(v>=0.70 for v in vals)/len(vals)
            # Ranking score favors actual local clear sky and footprint rescue; temporal distance is a mild penalty only.
            score=med*(float(r.gap_rescue_percent)/100.0)*math.exp(-0.08*dist)
            result.append({
              "snapshot":snap,
              "candidate_date":d,
              "gap_rescue_percent":float(r.gap_rescue_percent),
              "distance_days_to_frozen":dist,
              "sample_fields_with_data":len(vals),
              "median_clear_fraction":round(med,4),
              "p10_clear_fraction":round(p10,4),
              "fraction_samples_ge70pct_clear":round(clear70,4),
              "median_mean_cld":round(float(pd.Series(cld).median()),3) if cld else None,
              "combined_score":round(score,6),
            })

    rr=pd.DataFrame(result).sort_values(["snapshot","combined_score"],ascending=[True,False])
    rr.to_csv(out/"local_cloud_candidate_ranking.csv",index=False)
    summary=[]
    for snap in ("S2_2026_APRIL","S2_2026_JUNE"):
        top=rr[rr["snapshot"]==snap].head(5).to_dict(orient="records")
        summary.append({"snapshot":snap,"top5":top})
    (out/"local_cloud_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - LOCAL CLOUD VALIDATION")
    print(f"ACTUAL_PU_REPORTED={total_pu:.6f}")
    for s in summary:
        print(s["snapshot"])
        for i,r in enumerate(s["top5"],1):
            print(f'  {i}. {r["candidate_date"]} CLEAR_MED={r["median_clear_fraction"]:.4f} CLEAR_P10={r["p10_clear_fraction"]:.4f} RESCUE={r["gap_rescue_percent"]:.2f}% DIST={r["distance_days_to_frozen"]}d SCORE={r["combined_score"]:.6f}')
    print("OUTPUT="+str(out))
    print("FROZEN_SNAPSHOT_DATES_CHANGED=FALSE")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
