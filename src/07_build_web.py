#!/usr/bin/env python3
from pathlib import Path
import argparse,json,re,pandas as pd
from common import load_config, CSV_MUN_TO_UI, MUN_CODES, fmt_int_spaces

TOPO_KEEP=[
 "elev_mean_m","elev_p05_m","elev_p95_m","relief_p95_p05_m",
 "slope_mean_deg","slope_p90_deg","slope_p95_deg","slope_lt_1_pct",
 "slope_gt_3_pct","local_low50_lt_m0p25_pct","dem_coverage_pct"
]
TOPO_MAP=["elev_mean_m","slope_mean_deg","relief_p95_p05_m","local_low50_lt_m0p25_pct"]
HYDRO_KEEP=[
 "twi_coverage_pct","twi_mean","twi_sd","twi_p50","twi_p90","twi_p95","twi_p99",
 "twi_mean_pctile_all","twi_mean_pctile_mun","twi_p90_pctile_all","twi_p90_pctile_mun",
 "farmland_twi_p90_threshold","farmland_twi_p95_threshold",
 "twi_ge_farmland_p90_pct","twi_ge_farmland_p95_pct",
 "twi_ge_farmland_p90_pct_pctile_all","twi_ge_farmland_p90_pct_pctile_mun",
 "twi_ge_farmland_p95_pct_pctile_all","twi_ge_farmland_p95_pct_pctile_mun",
 "sca_p50_m","sca_p90_m","sca_p95_m","ln_sca_p50","ln_sca_p90","ln_sca_p95",
 "hydro_slope_mean_deg","hydro_slope_p90_deg","hydro_slope_p95_deg",
 "distance_to_mosaic_bbox_edge_m"
]
HYDRO_MAP=["twi_mean","twi_p90","twi_ge_farmland_p90_pct","twi_ge_farmland_p95_pct","ln_sca_p90"]


def jval(v):
 if pd.isna(v):return None
 return round(float(v),5)


def ui_name(name):
 """Translate legacy ASCII municipality names; already-correct UI names pass through."""
 return CSV_MUN_TO_UI.get(str(name),str(name))


def ranges_by_municipality(df,cols,municipalities):
 out={m:{} for m in municipalities}
 if "municipality" not in df.columns:return out
 for csvm,sub in df.groupby("municipality",dropna=True):
  ui=ui_name(csvm)
  if ui not in out:continue
  for c in cols:
   x=pd.to_numeric(sub[c],errors="coerce").dropna()
   out[ui][c]=([round(float(x.quantile(.05)),5),round(float(x.quantile(.95)),5)]
               if len(x) else [None,None])
 return out


def municipality_buttons(municipalities):
 """Generate municipality controls from data instead of hard-coding three towns."""
 rows=[]
 for m in municipalities:
  active=" active" if m=="Lomma" else ""
  rows.append(f'     <button class="mun{active}" data-mun="{m}">{m}</button>')
 return "\n".join(rows)


def main():
 ap=argparse.ArgumentParser();ap.add_argument("--config",default="config/local_paths.json")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1];cfg=load_config(root/a.config)
 d=root/cfg.get("build_dir","data/derived")
 dist=root/cfg.get("dist_dir","dist");dist.mkdir(parents=True,exist_ok=True)
 template=(root/"web"/"template_v092.html").read_text(encoding="utf-8")
 data=json.loads((d/"geometry_payload.json").read_text(encoding="utf-8"))
 soil=json.loads((d/"soil_payload.json").read_text(encoding="utf-8"))
 topo=pd.read_csv(d/"topography_features_blocks.csv",dtype={"blockid":str,"region_kod":str})
 hyd=pd.read_csv(d/"hydrology_features_final.csv",dtype={"blockid":str,"region_kod":str})

 # Stable Skåne ordering from common.py, with any unexpected payload keys appended.
 municipalities=[m for m in MUN_CODES if m in data]
 municipalities += [m for m in data if m not in municipalities]
 if "Lomma" not in municipalities:
  raise RuntimeError("Lomma saknas i geometry_payload; kan inte använda v0.92-startvy.")

 TOPO={m:{} for m in municipalities}
 TR=ranges_by_municipality(topo,TOPO_MAP,municipalities)
 for _,r in topo.iterrows():
  ui=ui_name(r.municipality)
  if ui in TOPO:TOPO[ui][str(r.blockid)]={c:jval(r.get(c)) for c in TOPO_KEEP}

 HYDRO={m:{} for m in municipalities}
 HR=ranges_by_municipality(hyd,HYDRO_MAP,municipalities)
 for _,r in hyd.iterrows():
  ui=ui_name(r.municipality)
  if ui in HYDRO:HYDRO[ui][str(r.blockid)]={c:jval(r.get(c)) for c in HYDRO_KEEP}

 p90=float(hyd.farmland_twi_p90_threshold.dropna().iloc[0])
 p95=float(hyd.farmland_twi_p95_threshold.dropna().iloc[0])
 ncell=int(pd.to_numeric(hyd.n_twi_cells,errors="coerce").fillna(0).sum())

 replacements={
  "__DATA_JSON__":json.dumps(data,ensure_ascii=False,separators=(",",":")),
  "__SOIL_JSON__":json.dumps(soil,ensure_ascii=False,separators=(",",":")),
  "__TOPO_JSON__":json.dumps(TOPO,ensure_ascii=False,separators=(",",":")),
  "__TOPO_RANGES_JSON__":json.dumps(TR,ensure_ascii=False,separators=(",",":")),
  "__HYDRO_JSON__":json.dumps(HYDRO,ensure_ascii=False,separators=(",",":")),
  "__HYDRO_RANGES_JSON__":json.dumps(HR,ensure_ascii=False,separators=(",",":")),
  "__FARMLAND_TWI_P90__":f"{p90:.6f}",
  "__FARMLAND_TWI_P95__":f"{p95:.6f}",
  "__FARMLAND_TWI_P90_2__":f"{p90:.2f}",
  "__FARMLAND_TWI_P95_2__":f"{p95:.2f}",
  "__FARMLAND_TWI_NCELLS_FMT__":fmt_int_spaces(ncell)
 }
 out=template
 for k,v in replacements.items():out=out.replace(k,v)

 # The HTML template remains the validated v0.92 shell. Replace its historical
 # three fixed municipality buttons during build so the generated MVP exposes
 # every municipality present in the Skåne payload.
 legacy='''   <div class="row" id="munBtns">\n     <button class="mun active" data-mun="Lomma">Lomma</button>\n     <button class="mun" data-mun="Kävlinge">Kävlinge</button>\n     <button class="mun" data-mun="Eslöv">Eslöv</button>\n   </div>'''
 generated='   <div class="row" id="munBtns">\n'+municipality_buttons(municipalities)+'\n   </div>'
 if legacy not in out:
  raise RuntimeError("Kunde inte hitta v0.92-kommunblock i HTML-templaten.")
 out=out.replace(legacy,generated,1)

 left=re.findall(r"__[A-Z0-9_]+__",out)
 if left:raise RuntimeError("Oersatta placeholders: "+str(sorted(set(left))))
 (dist/"index.html").write_text(out,encoding="utf-8")
 print("WEB BUILD: OK",dist/"index.html",f"{(dist/'index.html').stat().st_size/1024/1024:.1f} MB",
       f"kommuner={len(municipalities)}")


if __name__=="__main__":main()
