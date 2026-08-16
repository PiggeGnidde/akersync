#!/usr/bin/env python3
from pathlib import Path
import argparse,pandas as pd
from common import load_config


def audited_subpixel_ids(d: Path, missing_ids: set[str]) -> tuple[bool,set[str],str]:
 audit_path=d/"hydrology_missing_blocks_audit.csv"
 if not missing_ids:
  return True,set(),"inga saknade hydrologiblock"
 if not audit_path.exists():
  return False,set(),f"audit saknas: {audit_path}"
 audit=pd.read_csv(audit_path,dtype={"blockid":str,"region_kod":str})
 if not {"blockid","reason"}.issubset(audit.columns):
  return False,set(),"audit saknar blockid/reason"
 audit["blockid"]=audit.blockid.astype(str)
 audit_ids=set(audit.blockid)
 if audit_ids!=missing_ids:
  return False,audit_ids,f"audit-id matchar inte saknade: audit={len(audit_ids)}, saknade={len(missing_ids)}"
 if not bool((audit.reason.astype(str)=="SUBPIXEL_10M").all()):
  return False,audit_ids,"minst ett saknat block har annan diagnos än SUBPIXEL_10M"
 if "dem_inside_centres" in audit.columns:
  centres=pd.to_numeric(audit.dem_inside_centres,errors="coerce")
  if not bool((centres==0).all()):
   return False,audit_ids,"SUBPIXEL-audit innehåller block med DEM-cellcentrum"
 total_area=float(pd.to_numeric(audit.get("area_ha",pd.Series(dtype=float)),errors="coerce").fillna(0).sum())
 if len(audit)>12 or total_area>0.10:
  return False,audit_ids,f"för många/stora undantag för automatisk acceptans: n={len(audit)}, area={total_area:.6f} ha"
 return True,audit_ids,f"{len(audit)} auditerade SUBPIXEL_10M, total area {total_area:.6f} ha"


def main():
 ap=argparse.ArgumentParser();ap.add_argument("--config",default="config/local_paths.json")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1];cfg=load_config(root/a.config)
 d=root/cfg.get("build_dir","data/derived")
 hyd=pd.read_csv(d/"hydrology_features_blocks.csv",dtype={"blockid":str,"region_kod":str})
 farm=pd.read_csv(d/"hydrology_features_farmland_thresholds.csv",dtype={"blockid":str,"region_kod":str})
 x=hyd.merge(farm,on=["blockid","region_kod"],how="left",validate="one_to_one")
 if len(x)!=len(hyd) or len(farm)!=len(hyd):
  raise RuntimeError(
   f"Hydrology/farmland merge misslyckades: hyd={len(hyd)}, farm={len(farm)}, merged={len(x)}"
  )

 missing_h=set(x.loc[pd.to_numeric(x.twi_mean,errors="coerce").isna(),"blockid"].astype(str))
 missing_f=set(x.loc[pd.to_numeric(x.twi_ge_farmland_p90_pct,errors="coerce").isna(),"blockid"].astype(str))
 missing=missing_h|missing_f
 if missing_h!=missing_f:
  raise RuntimeError(
   f"Olika block saknar hydrologi/farmland-TWI: hyd={sorted(missing_h)}, farmland={sorted(missing_f)}"
  )
 audit_ok,audit_ids,audit_msg=audited_subpixel_ids(d,missing)
 if not audit_ok:
  raise RuntimeError("Hydrologi saknas utan godkänd subpixel-audit: "+audit_msg)
 if missing:
  print("Hydrology subpixel exceptions: OK —",audit_msg)

 for col in ["twi_mean","twi_p90","twi_ge_farmland_p90_pct","twi_ge_farmland_p95_pct"]:
  x[f"{col}_pctile_all"]=100*x[col].rank(method="average",pct=True)
  x[f"{col}_pctile_mun"]=x.groupby("municipality")[col].rank(method="average",pct=True)*100
 x.to_csv(d/"hydrology_features_final.csv",index=False,encoding="utf-8-sig")
 print("Hydrology final: OK",d/"hydrology_features_final.csv",f"({len(x)} block; {len(missing)} auditerade subpixel-undantag)")

if __name__=="__main__":main()
