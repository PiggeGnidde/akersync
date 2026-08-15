#!/usr/bin/env python3
from pathlib import Path
import argparse, json
import geopandas as gpd
from common import load_config, MUN_CODES, save_json

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--config",default="config/local_paths.json")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1]
 cfg=load_config(root/a.config)
 outdir=root/cfg.get("build_dir","data/derived"); outdir.mkdir(parents=True,exist_ok=True)

 blocks=gpd.read_file(cfg["blocks"]).to_crs(3006)
 skiften=gpd.read_file(cfg["skiften"]).to_crs(3006)

 parent=blocks.set_index(blocks.blockid.astype(str)).geometry.to_dict()
 inside=[]; overflow=[]
 for _,r in skiften.iterrows():
  p=parent.get(str(r.blockid))
  if p is None or r.geometry is None or r.geometry.is_empty or r.geometry.area<=0:
   inside.append(None); overflow.append(None); continue
  inter=r.geometry.intersection(p).area
  inside.append(100.0*inter/r.geometry.area)
  overflow.append(max(0.0,r.geometry.area-inter))
 skiften=skiften.copy()
 skiften["inside_pct"]=inside; skiften["overflow_m2"]=overflow
 skiften["alignment_warning"]=(skiften.inside_pct<99.0)|(skiften.overflow_m2>250)

 payload={}
 summary=[]
 for name,code in MUN_CODES.items():
  b=blocks[blocks.region_kod.astype(str).str.startswith(code)].copy()
  s=skiften[skiften.blockid.isin(b.blockid)].copy()
  summary.append({"kommun":name,"blocks":len(b),"skiften":len(s),
                  "alignment_warnings":int(s.alignment_warning.fillna(False).sum())})
  b.geometry=b.geometry.simplify(.20,preserve_topology=True)
  s.geometry=s.geometry.simplify(.20,preserve_topology=True)
  b=b.to_crs(4326); s=s.to_crs(4326)
  bcols=["blockid","region_kod","kategori","agoslag","areal","geometry"]
  scols=["blockid","skiftesbeteckning","grdkod_mar","grdkod_und",
         "ansokt_areal_ha","faststalld_areal_ha","inside_pct",
         "overflow_m2","alignment_warning","geometry"]
  payload[name]={
   "blocks":json.loads(b[bcols].to_json(drop_id=True)),
   "skiften":json.loads(s[scols].to_json(drop_id=True))
  }

 save_json(payload,outdir/"geometry_payload.json")
 import pandas as pd
 pd.DataFrame(summary).to_csv(outdir/"geometry_summary.csv",index=False,encoding="utf-8-sig")
 print("Geometry: OK",outdir/"geometry_payload.json")

if __name__=="__main__": main()
