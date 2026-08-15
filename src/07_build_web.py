#!/usr/bin/env python3
from pathlib import Path
import argparse,json,re,unicodedata
import pandas as pd
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
 return CSV_MUN_TO_UI.get(str(name),str(name))


def safe_slug(name):
 s=unicodedata.normalize("NFKD",name).encode("ascii","ignore").decode("ascii").lower()
 return re.sub(r"[^a-z0-9]+","-",s).strip("-")


def municipality_filename(name):
 return f"{MUN_CODES.get(name,'0000')}_{safe_slug(name)}.html"


def ranges_for(df,cols,mun):
 out={mun:{}}
 if "municipality" not in df.columns:return out
 sub=df[df.municipality.map(ui_name)==mun]
 for c in cols:
  x=pd.to_numeric(sub[c],errors="coerce").dropna()
  out[mun][c]=([round(float(x.quantile(.05)),5),round(float(x.quantile(.95)),5)]
               if len(x) else [None,None])
 return out


def feature_dict(df,keep,mun):
 out={mun:{}}
 sub=df[df.municipality.map(ui_name)==mun]
 for _,r in sub.iterrows():
  out[mun][str(r.blockid)]={c:jval(r.get(c)) for c in keep}
 return out


def render_page(template,mun,data,soil,topo,hyd,p90,p95,ncell):
 topo_obj=feature_dict(topo,TOPO_KEEP,mun)
 hydro_obj=feature_dict(hyd,HYDRO_KEEP,mun)
 tr=ranges_for(topo,TOPO_MAP,mun)
 hr=ranges_for(hyd,HYDRO_MAP,mun)
 replacements={
  "__DATA_JSON__":json.dumps({mun:data[mun]},ensure_ascii=False,separators=(",",":")),
  "__SOIL_JSON__":json.dumps({mun:soil[mun]},ensure_ascii=False,separators=(",",":")),
  "__TOPO_JSON__":json.dumps(topo_obj,ensure_ascii=False,separators=(",",":")),
  "__TOPO_RANGES_JSON__":json.dumps(tr,ensure_ascii=False,separators=(",",":")),
  "__HYDRO_JSON__":json.dumps(hydro_obj,ensure_ascii=False,separators=(",",":")),
  "__HYDRO_RANGES_JSON__":json.dumps(hr,ensure_ascii=False,separators=(",",":")),
  "__FARMLAND_TWI_P90__":f"{p90:.6f}",
  "__FARMLAND_TWI_P95__":f"{p95:.6f}",
  "__FARMLAND_TWI_P90_2__":f"{p90:.2f}",
  "__FARMLAND_TWI_P95_2__":f"{p95:.2f}",
  "__FARMLAND_TWI_NCELLS_FMT__":fmt_int_spaces(ncell)
 }
 out=template
 for k,v in replacements.items():out=out.replace(k,v)

 # Keep the validated v0.92 map shell, but make each generated page contain
 # only one municipality.  This avoids a several-hundred-MB monolithic HTML
 # when scaling from three municipalities to all of Skåne.
 legacy='''   <div class="row" id="munBtns">\n     <button class="mun active" data-mun="Lomma">Lomma</button>\n     <button class="mun" data-mun="Kävlinge">Kävlinge</button>\n     <button class="mun" data-mun="Eslöv">Eslöv</button>\n   </div>'''
 single=(f'   <div class="row" id="munBtns">\n'
         f'     <a class="actionBtn" href="../index.html" style="text-decoration:none;color:#111">← Skåne</a>\n'
         f'     <button class="mun active" data-mun="{mun}">{mun}</button>\n'
         f'   </div>')
 if legacy not in out:raise RuntimeError("Kunde inte hitta v0.92-kommunblock i HTML-templaten.")
 out=out.replace(legacy,single,1)
 out=out.replace('ÅkerSync v0.92 · Lomma',f'ÅkerSync v0.92 · {mun}',1)
 out=out.replace("let currentMun='Lomma'",f"let currentMun={json.dumps(mun,ensure_ascii=False)}",1)
 out=out.replace("renderMunicipality('Lomma');",f"renderMunicipality({json.dumps(mun,ensure_ascii=False)});",1)

 left=re.findall(r"__[A-Z0-9_]+__",out)
 if left:raise RuntimeError("Oersatta placeholders: "+str(sorted(set(left))))
 return out


def landing_page(municipalities,data):
 total_b=sum(len(data[m]["blocks"]["features"]) for m in municipalities)
 total_s=sum(len(data[m]["skiften"]["features"]) for m in municipalities)
 cards=[]
 for m in municipalities:
  nb=len(data[m]["blocks"]["features"]);ns=len(data[m]["skiften"]["features"])
  cards.append(f'<a class="card" href="municipalities/{municipality_filename(m)}"><b>{m}</b><span>{nb:,} block · {ns:,} skiften</span></a>'.replace(","," "))
 return f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ÅkerSync · Skåne</title><style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#f4f4f1;color:#171717}}main{{max-width:1000px;margin:auto;padding:28px 18px 60px}}h1{{margin-bottom:4px}}.lead{{color:#555;margin-top:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-top:24px}}.card{{display:flex;flex-direction:column;gap:4px;padding:14px 16px;background:white;border:1px solid #ddd;border-radius:10px;color:#111;text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,.06)}}.card:hover{{border-color:#777}}.card span{{font-size:13px;color:#555}}</style></head><body><main><h1>ÅkerSync · Skåne MVP</h1><p class="lead">{len(municipalities)} kommuner · {total_b:,} jordbruksblock · {total_s:,} skiften. Välj kommun för den interaktiva fältkartan.</p><div class="grid">{''.join(cards)}</div></main></body></html>'''.replace(f'{total_b:,}',f'{total_b:,}'.replace(',',' ')).replace(f'{total_s:,}',f'{total_s:,}'.replace(',',' '))


def main():
 ap=argparse.ArgumentParser();ap.add_argument("--config",default="config/local_paths.json")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1];cfg=load_config(root/a.config)
 d=root/cfg.get("build_dir","data/derived")
 dist=root/cfg.get("dist_dir","dist");dist.mkdir(parents=True,exist_ok=True)
 pages=dist/"municipalities";pages.mkdir(parents=True,exist_ok=True)
 template=(root/"web"/"template_v092.html").read_text(encoding="utf-8")
 data=json.loads((d/"geometry_payload.json").read_text(encoding="utf-8"))
 soil=json.loads((d/"soil_payload.json").read_text(encoding="utf-8"))
 topo=pd.read_csv(d/"topography_features_blocks.csv",dtype={"blockid":str,"region_kod":str})
 hyd=pd.read_csv(d/"hydrology_features_final.csv",dtype={"blockid":str,"region_kod":str})
 municipalities=[m for m in MUN_CODES if m in data]
 missing=set(MUN_CODES)-set(municipalities)
 if missing:raise RuntimeError("Kommuner saknas i geometry_payload: "+", ".join(sorted(missing)))

 p90=float(hyd.farmland_twi_p90_threshold.dropna().iloc[0])
 p95=float(hyd.farmland_twi_p95_threshold.dropna().iloc[0])
 ncell=int(pd.to_numeric(hyd.n_twi_cells,errors="coerce").fillna(0).sum())

 sizes=[]
 for mun in municipalities:
  html=render_page(template,mun,data,soil,topo,hyd,p90,p95,ncell)
  path=pages/municipality_filename(mun);path.write_text(html,encoding="utf-8")
  sizes.append(path.stat().st_size)
  print(f"  {mun:16s} {path.name:28s} {path.stat().st_size/1024/1024:6.1f} MB")

 (dist/"index.html").write_text(landing_page(municipalities,data),encoding="utf-8")
 manifest={m:{"code":MUN_CODES[m],"file":"municipalities/"+municipality_filename(m),
              "blocks":len(data[m]["blocks"]["features"]),"skiften":len(data[m]["skiften"]["features"])}
           for m in municipalities}
 (dist/"municipalities.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
 print(f"WEB BUILD: OK · {len(municipalities)} kommuner · total {sum(sizes)/1024/1024:.1f} MB · maxsida {max(sizes)/1024/1024:.1f} MB")
 print("Landing:",dist/"index.html")


if __name__=="__main__":main()
