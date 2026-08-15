#!/usr/bin/env python3
from pathlib import Path
import argparse, numpy as np, pandas as pd, geopandas as gpd, rasterio
from rasterio.features import rasterize, geometry_mask
from rasterio.windows import from_bounds
from common import load_config, MUN_CODES

def vals_for_geom(ds,geom):
 w=from_bounds(*geom.bounds,transform=ds.transform)
 c0=max(0,int(np.floor(w.col_off)));r0=max(0,int(np.floor(w.row_off)))
 c1=min(ds.width,int(np.ceil(w.col_off+w.width)));r1=min(ds.height,int(np.ceil(w.row_off+w.height)))
 if c1<=c0 or r1<=r0:return np.array([],dtype=np.float32)
 win=rasterio.windows.Window(c0,r0,c1-c0,r1-r0)
 tr=rasterio.windows.transform(win,ds.transform)
 inside=geometry_mask([geom.__geo_interface__],out_shape=(int(win.height),int(win.width)),
                      transform=tr,invert=True,all_touched=False)
 a=ds.read(1,window=win,masked=False)
 ok=inside & np.isfinite(a)
 if ds.nodata is not None:ok &= a!=ds.nodata
 return a[ok].astype(np.float32)

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--config",default="config/local_paths.json")
 ap.add_argument("--twi",required=True)
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1];cfg=load_config(root/a.config)
 outdir=root/cfg.get("build_dir","data/derived");outdir.mkdir(parents=True,exist_ok=True)
 blocks=gpd.read_file(cfg["blocks"]).to_crs(3006)
 blocks=blocks[blocks.region_kod.astype(str).str.startswith(tuple(MUN_CODES.values()))].copy()
 with rasterio.open(a.twi) as ds:
  shapes=((g.__geo_interface__,1) for g in blocks.geometry if g is not None and not g.is_empty)
  farmmask=rasterize(shapes,out_shape=(ds.height,ds.width),transform=ds.transform,
                     fill=0,dtype="uint8",all_touched=False)
  arr=ds.read(1,masked=False)
  ok=(farmmask==1)&np.isfinite(arr)
  if ds.nodata is not None:ok &= arr!=ds.nodata
  vals=arr[ok].astype(np.float32)
  if vals.size==0:raise RuntimeError("Inga TWI-celler inom åkermark.")
  p90=float(np.percentile(vals,90));p95=float(np.percentile(vals,95))
  rows=[]
  for j,(_,r) in enumerate(blocks.iterrows(),1):
   v=vals_for_geom(ds,r.geometry)
   rows.append({"blockid":str(r.blockid),"region_kod":str(r.region_kod),
    "farmland_twi_p90_threshold":p90,"farmland_twi_p95_threshold":p95,
    "twi_ge_farmland_p90_pct":100*np.mean(v>=p90) if v.size else np.nan,
    "twi_ge_farmland_p95_pct":100*np.mean(v>=p95) if v.size else np.nan,
    "n_twi_cells":int(v.size)})
   if j%500==0 or j==len(blocks):print(f"\rFarmland TWI {j}/{len(blocks)}",end="",flush=True)
  print()
 pd.DataFrame(rows).to_csv(outdir/"hydrology_features_farmland_thresholds.csv",index=False,encoding="utf-8-sig")
 (outdir/"farmland_twi_thresholds.txt").write_text(
  f"Farmland-only TWI thresholds\nP90={p90:.6f}\nP95={p95:.6f}\nFarmland cells={vals.size}\n",
  encoding="utf-8")
 print("Farmland TWI:",p90,p95,"cells",vals.size)

if __name__=="__main__":main()
