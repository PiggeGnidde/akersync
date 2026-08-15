#!/usr/bin/env python3
from pathlib import Path
import argparse, base64, io, json, math, tempfile, zipfile
import numpy as np, pandas as pd, geopandas as gpd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, Window
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import array_bounds
from pyproj import Transformer
from PIL import Image
from common import load_config, MUN_CODES, save_json

ORG_LABELS={2:"<2,5 %",3:"2,5–3,5 %",4:"3,5–4,5 %",5:"4,5–5,5 %",
            6:"5,5–6,5 %",9:"6,5–12 %",16:"12–20 %",30:"≥20 %"}
ORG_CODES=[2,3,4,5,6,9,16,30]
ORG_COLORS={2:(56,161,208),3:(135,186,188),4:(181,211,165),5:(222,238,139),
            6:(246,226,109),9:(249,175,80),16:(247,120,50),30:(137,68,68)}
CONT_COLORS=[(215,25,28),(253,189,115),(255,255,191),(163,215,165),(43,131,186)]

def geom_window(bounds, transform, width, height):
 w=from_bounds(*bounds,transform=transform)
 c0=max(0,int(math.floor(w.col_off))); r0=max(0,int(math.floor(w.row_off)))
 c1=min(width,int(math.ceil(w.col_off+w.width))); r1=min(height,int(math.ceil(w.row_off+w.height)))
 if c1<=c0 or r1<=r0:return None
 return Window(c0,r0,c1-c0,r1-r0)

def vals_in_geom(geom,arr,tr,nodata):
 if geom is None or geom.is_empty or geom.area<=0:return np.array([]),0.0
 w=geom_window(geom.bounds,tr,arr.shape[1],arr.shape[0])
 if w is None:return np.array([]),0.0
 r0,c0,h,ww=int(w.row_off),int(w.col_off),int(w.height),int(w.width)
 sub=arr[r0:r0+h,c0:c0+ww]
 subtr=rasterio.windows.transform(w,tr)
 mask=geometry_mask([geom.__geo_interface__],out_shape=sub.shape,transform=subtr,
                    invert=True,all_touched=False)
 ok=mask & np.isfinite(sub)
 if nodata is not None:ok &= sub!=nodata
 vals=sub[ok].astype(float)
 pixarea=abs(tr.a*tr.e)
 cov=min(100.0, vals.size*pixarea/geom.area*100.0) if geom.area else 0
 return vals,cov

def continuous_stats(geom,arr,tr,nodata):
 vals,cov=vals_in_geom(geom,arr,tr,nodata)
 if vals.size==0:return [None,None,None,None,None,None,0.0,0]
 q=np.percentile(vals,[10,50,90])
 inner=geom.buffer(-10)
 iv,_=vals_in_geom(inner,arr,tr,nodata) if not inner.is_empty else (np.array([]),0)
 im=float(iv.mean()) if iv.size else None
 def c(x):return None if x is None else round(float(x),2)
 return [c(vals.mean()),c(vals.std()),c(q[0]),c(q[1]),c(q[2]),c(im),c(cov),int(vals.size)]

def organic_stats(geom,arr,tr,nodata):
 vals,cov=vals_in_geom(geom,arr,tr,nodata)
 if vals.size==0:return [None,None,0.0,0]+[0.0]*8
 vals=vals.astype(int)
 counts={c:int(np.sum(vals==c)) for c in ORG_CODES}
 mode=max(ORG_CODES,key=lambda c:(counts[c],-ORG_CODES.index(c)))
 shares=[100.0*counts[c]/vals.size for c in ORG_CODES]
 ge20=shares[-1]
 return [int(mode),round(ge20,2),round(cov,2),int(vals.size)]+[round(x,2) for x in shares]

def colorize_cont(arr,nodata,vmin,vmax):
 x=np.clip((arr.astype(float)-vmin)/(vmax-vmin),0,1)
 stops=np.linspace(0,1,len(CONT_COLORS))
 rgba=np.zeros(arr.shape+(4,),dtype=np.uint8)
 for k in range(3):rgba[...,k]=np.interp(x,stops,[c[k] for c in CONT_COLORS]).astype(np.uint8)
 valid=np.isfinite(arr)
 if nodata is not None:valid &= arr!=nodata
 rgba[...,3]=np.where(valid,190,0).astype(np.uint8)
 return rgba

def colorize_org(arr,nodata):
 rgba=np.zeros(arr.shape+(4,),dtype=np.uint8)
 for code,color in ORG_COLORS.items():
  m=arr==code
  rgba[m,0]=color[0];rgba[m,1]=color[1];rgba[m,2]=color[2];rgba[m,3]=190
 return rgba

def overlay(ds, b, arr, tr, nodata, kind):
 left,bottom,right,top=array_bounds(arr.shape[0],arr.shape[1],tr)
 dst_tr,dw,dh=calculate_default_transform(ds.crs,"EPSG:3857",arr.shape[1],arr.shape[0],
                                           left,bottom,right,top)
 fill=int(nodata) if nodata is not None else 0
 dst=np.full((dh,dw),fill,dtype=arr.dtype)
 reproject(source=arr,destination=dst,src_transform=tr,src_crs=ds.crs,
           src_nodata=nodata,dst_transform=dst_tr,dst_crs="EPSG:3857",
           dst_nodata=nodata,resampling=Resampling.nearest)
 if kind=="organic":rgba=colorize_org(dst,nodata)
 else:rgba=colorize_cont(dst,nodata,1,65 if kind=="clay" else 90)
 buf=io.BytesIO();Image.fromarray(rgba,"RGBA").save(buf,format="PNG",optimize=True)
 l,bm,r,t=array_bounds(dst.shape[0],dst.shape[1],dst_tr)
 tf=Transformer.from_crs(3857,4326,always_xy=True)
 west,south=tf.transform(l,bm);east,north=tf.transform(r,t)
 return {"image":"data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode("ascii"),
         "bounds":[[south,west],[north,east]]}

def extract_member(z,basename,td):
 member=next((n for n in z.namelist() if n.endswith("/"+basename) or n==basename),None)
 if not member:raise RuntimeError("Saknar "+basename)
 z.extract(member,td)
 return Path(td)/member

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--config",default="config/local_paths.json")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1];cfg=load_config(root/a.config)
 outdir=root/cfg.get("build_dir","data/derived");outdir.mkdir(parents=True,exist_ok=True)
 blocks=gpd.read_file(cfg["blocks"]).to_crs(3006)
 skiften=gpd.read_file(cfg["skiften"]).to_crs(3006)
 layers={"clay":"dsms2025_ler.tif","sand":"dsms2025_sand.tif",
         "silt":"dsms2025_silt.tif","organic":"dsms2025_organisk_klasser.tif"}
 payload={m:{"overlays":{},"blocks":{},"skiften":{}} for m in MUN_CODES}
 block_rows={};field_rows={}

 with tempfile.TemporaryDirectory() as td,zipfile.ZipFile(cfg["soil_zip"]) as z:
  for kind,base in layers.items():
   p=extract_member(z,base,td)
   print("Soil layer:",kind,p.name)
   with rasterio.open(p) as ds:
    crs_text=str(ds.crs)
    is_sweref99tm=(ds.crs.to_epsg()==3006) or ('AUTHORITY["EPSG","3006"]' in crs_text) or ('SWEREF99 TM' in crs_text)
    if (not is_sweref99tm) or tuple(ds.res)!=(20.0,20.0):
     raise RuntimeError(f"{base}: väntade SWEREF99 TM/EPSG:3006, 20m, fick {ds.crs} {ds.res}")
    for mun,code in MUN_CODES.items():
     b=blocks[blocks.region_kod.astype(str).str.startswith(code)].copy()
     s=skiften[skiften.blockid.isin(b.blockid)].copy()
     x0,y0,x1,y1=b.total_bounds
     w=from_bounds(x0-20,y0-20,x1+20,y1+20,transform=ds.transform).round_offsets().round_lengths()
     w=w.intersection(Window(0,0,ds.width,ds.height))
     arr=ds.read(1,window=w);tr=ds.window_transform(w);nodata=ds.nodata
     payload[mun]["overlays"][kind]=overlay(ds,b,arr,tr,nodata,kind)
     print(f"  {mun}: {len(b)} block + {len(s)} skiften")
     for _,r in b.iterrows():
      key=str(r.blockid); block_rows.setdefault((mun,key),{"kommun":mun,"blockid":key,"area_ha":r.geometry.area/10000})
      st=organic_stats(r.geometry,arr,tr,nodata) if kind=="organic" else continuous_stats(r.geometry,arr,tr,nodata)
      payload[mun]["blocks"].setdefault(key,{})[kind]=st
     for _,r in s.iterrows():
      key=f"{r.blockid}|{r.skiftesbeteckning}"
      field_rows.setdefault((mun,key),{"kommun":mun,"blockid":str(r.blockid),
        "skiftesbeteckning":r.skiftesbeteckning,"crop_code":r.grdkod_mar,
        "area_ha":r.geometry.area/10000})
      st=organic_stats(r.geometry,arr,tr,nodata) if kind=="organic" else continuous_stats(r.geometry,arr,tr,nodata)
      payload[mun]["skiften"].setdefault(key,{})[kind]=st

 # Flatten features for regression/QA.
 def add_flat(row,st):
  for kind in ("clay","sand","silt"):
   a=st.get(kind,[None]*8)
   for nm,val in zip(["mean","sd","p10","p50","p90","inner10_mean","coverage_pct","n_pix"],a):
    row[f"{kind}_{nm}"]=val
  o=st.get("organic",[None,None,None,None]+[None]*8)
  row["organic_mode_code"]=o[0];row["organic_mode_label"]=ORG_LABELS.get(o[0],"")
  row["organic_ge20_share_pct"]=o[1];row["organic_coverage_pct"]=o[2];row["organic_n_pix"]=o[3]
  for code,val in zip(ORG_CODES,o[4:]):row[f"organic_share_code_{code}_pct"]=val
  vals=[row.get("clay_mean"),row.get("sand_mean"),row.get("silt_mean")]
  row["texture_sum_mean_pct"]=sum(vals) if all(v is not None for v in vals) else None
  return row

 bout=[];sout=[]
 for (mun,key),r in block_rows.items():bout.append(add_flat(r,payload[mun]["blocks"][key]))
 for (mun,key),r in field_rows.items():sout.append(add_flat(r,payload[mun]["skiften"][key]))
 bdf=pd.DataFrame(bout);sdf=pd.DataFrame(sout)
 bdf.to_csv(outdir/"soil_features_blocks.csv",index=False,encoding="utf-8-sig")
 sdf.to_csv(outdir/"soil_features_skiften.csv",index=False,encoding="utf-8-sig")
 summary=[]
 for mun in MUN_CODES:
  x=bdf[bdf.kommun==mun];y=sdf[sdf.kommun==mun]
  summary.append({"kommun":mun,"blocks":len(x),"skiften":len(y),
   "skiften_med_texturdata":int(y.clay_mean.notna().sum()),
   "median_clay_mean_pct":x.clay_mean.median(),
   "median_sand_mean_pct":x.sand_mean.median(),
   "median_silt_mean_pct":x.silt_mean.median(),
   "median_texture_sum_pct":x.texture_sum_mean_pct.median(),
   "median_abs_texture_sum_error_pct":(x.texture_sum_mean_pct-100).abs().median(),
   "median_clay_coverage_pct":x.clay_coverage_pct.median(),
   "fields_with_any_ge20_organic":int((y.organic_ge20_share_pct>0).sum())})
 pd.DataFrame(summary).to_csv(outdir/"soil_summary.csv",index=False,encoding="utf-8-sig")
 save_json(payload,outdir/"soil_payload.json")
 print("Soil: OK",outdir/"soil_payload.json")

if __name__=="__main__":main()
