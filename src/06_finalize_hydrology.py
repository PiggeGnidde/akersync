#!/usr/bin/env python3
from pathlib import Path
import argparse,pandas as pd
from common import load_config

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--config",default="config/local_paths.json")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1];cfg=load_config(root/a.config)
 d=root/cfg.get("build_dir","data/derived")
 hyd=pd.read_csv(d/"hydrology_features_blocks.csv",dtype={"blockid":str,"region_kod":str})
 farm=pd.read_csv(d/"hydrology_features_farmland_thresholds.csv",dtype={"blockid":str,"region_kod":str})
 x=hyd.merge(farm,on=["blockid","region_kod"],how="left",validate="one_to_one")
 if len(x)!=len(hyd) or len(farm)!=len(hyd) or x.twi_ge_farmland_p90_pct.isna().any():
  raise RuntimeError(
   f"Hydrology/farmland merge misslyckades: hyd={len(hyd)}, farm={len(farm)}, merged={len(x)}"
  )
 for col in ["twi_mean","twi_p90","twi_ge_farmland_p90_pct","twi_ge_farmland_p95_pct"]:
  x[f"{col}_pctile_all"]=100*x[col].rank(method="average",pct=True)
  x[f"{col}_pctile_mun"]=x.groupby("municipality")[col].rank(method="average",pct=True)*100
 x.to_csv(d/"hydrology_features_final.csv",index=False,encoding="utf-8-sig")
 print("Hydrology final: OK",d/"hydrology_features_final.csv",f"({len(x)} block)")

if __name__=="__main__":main()
