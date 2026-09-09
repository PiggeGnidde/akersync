#!/usr/bin/env python3
"""STOPPUNKT B1: bounded 10 m Sentinel-2 rasters for the compact 2026 geometry pilot."""
from __future__ import annotations
import argparse, hashlib, json, math, os, urllib.error, urllib.parse, urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
MASTER=ROOT/"config"/"akerpuls_prelim_fields_2026_v0.json"
B1CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b1.json"
PROCESS_URL="https://sh.dataspace.copernicus.eu/process/v1"
CRS_URI="http://www.opengis.net/def/crs/EPSG/0/32633"
SOURCE_BANDS=["B02","B03","B04","B08","B11","SCL","CLD","dataMask"]
SNAPSHOT_BANDS=["B02","B03","B04","B08","B11","SCL","CLD","VALID","NDVI","LSWI","SOURCE_DATE_INDEX"]

def stable(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(v): return hashlib.sha256(v).hexdigest()

def oauth(master):
    cid=os.getenv("CDSE_CLIENT_ID","").strip(); sec=os.getenv("CDSE_CLIENT_SECRET","").strip()
    if not cid or not sec: raise RuntimeError("BLOCKED_CREDENTIALS: CDSE_CLIENT_ID/CDSE_CLIENT_SECRET are not set")
    body=urllib.parse.urlencode({"grant_type":"client_credentials","client_id":cid,"client_secret":sec}).encode()
    req=urllib.request.Request(master["sentinel2"]["token_url"],data=body,method="POST",headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read().decode())["access_token"]

def evalscript():
    return """//VERSION=3
function setup(){
  return {
    input:[{bands:["B02","B03","B04","B08","B11","SCL","CLD","dataMask"],units:"REFLECTANCE"}],
    output:{bands:8,sampleType:"FLOAT32"}
  };
}
function evaluatePixel(s){
  return [s.B02,s.B03,s.B04,s.B08,s.B11,s.SCL,s.CLD,s.dataMask];
}"""

def payload(day,bbox,width,height):
    d=date.fromisoformat(day); e=d+timedelta(days=1)
    return {
      "input":{"bounds":{"bbox":[float(x) for x in bbox],"properties":{"crs":CRS_URI}},
               "data":[{"type":"sentinel-2-l2a",
                        "dataFilter":{"timeRange":{"from":f"{d}T00:00:00Z","to":f"{e}T00:00:00Z"},"maxCloudCoverage":100},
                        "processing":{"upsampling":"BILINEAR","downsampling":"BILINEAR","harmonizeValues":True}}]},
      "output":{"width":int(width),"height":int(height),
                "responses":[{"identifier":"default","format":{"type":"image/tiff"}}]},
      "evalscript":evalscript()
    }

def fetch_tiff(token,p,out):
    raw=(stable(p)+"\n").encode(); reqhash=sha(raw)
    meta=out.with_suffix(out.suffix+".json")
    if out.exists() and meta.exists():
        m=json.loads(meta.read_text(encoding="utf-8"))
        if m.get("request_sha256")!=reqhash: raise RuntimeError(f"Cached request mismatch: {out}")
        if sha(out.read_bytes())!=m.get("response_sha256"): raise RuntimeError(f"Cached response mismatch: {out}")
        return m, True
    req=urllib.request.Request(PROCESS_URL,data=raw,method="POST",headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","Accept":"image/tiff"})
    try:
        with urllib.request.urlopen(req,timeout=240) as r:
            body=r.read(); pu=r.headers.get("x-processingunits-spent")
    except urllib.error.HTTPError as exc:
        msg=exc.read().decode("utf-8","replace")[:1000]
        raise RuntimeError(f"Process API HTTP {exc.code}: {msg}") from exc
    out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(body)
    m={"request_sha256":reqhash,"response_sha256":sha(body),"bytes":len(body),
       "reported_pu":float(pu) if pu not in (None,"") else None,
       "created_utc":datetime.now(timezone.utc).isoformat()}
    meta.write_text(json.dumps(m,indent=2)+"\n",encoding="utf-8")
    return m, False

def aligned_bounds(bounds,res,buffer_m):
    minx,miny,maxx,maxy=bounds
    minx=math.floor((minx-buffer_m)/res)*res
    miny=math.floor((miny-buffer_m)/res)*res
    maxx=math.ceil((maxx+buffer_m)/res)*res
    maxy=math.ceil((maxy+buffer_m)/res)*res
    return (minx,miny,maxx,maxy)

def read_source(path,expected_width,expected_height):
    import rasterio
    with rasterio.open(path) as ds:
        arr=ds.read().astype("float32")
        if arr.shape!=(8,expected_height,expected_width):
            raise RuntimeError(f"{path.name}: unexpected shape {arr.shape}")
        return arr,ds.transform,ds.crs

def choose_pair(arrays,clear_codes):
    if len(arrays)==1:
        a=arrays[0]; choice=np.zeros(a.shape[1:],dtype=np.int16)
    elif len(arrays)==2:
        a,b=arrays
        d1=a[7]>0.5; d2=b[7]>0.5
        c1=d1 & np.isin(np.rint(a[5]).astype(np.int16),list(clear_codes))
        c2=d2 & np.isin(np.rint(b[5]).astype(np.int16),list(clear_codes))
        # date2 wins only if it is clear while date1 is not, or ties are broken by lower CLD.
        choose2=(c2 & ~c1) | ((c1==c2) & d2 & (~d1 | (b[6]<a[6])))
        choice=choose2.astype(np.int16)
        a=np.where(choose2[None,:,:],b,a)
    else:
        raise RuntimeError("Only one- or two-day frozen snapshots are supported")
    scl=np.rint(a[5]).astype(np.int16); dat=a[7]>0.5
    valid=dat & np.isin(scl,list(clear_codes))
    den=a[3]+a[2]; ndvi=np.divide(a[3]-a[2],den,out=np.zeros_like(den),where=np.abs(den)>1e-8)
    den2=a[3]+a[4]; lswi=np.divide(a[3]-a[4],den2,out=np.zeros_like(den2),where=np.abs(den2)>1e-8)
    return np.stack([a[0],a[1],a[2],a[3],a[4],a[5],a[6],valid.astype("float32"),
                     ndvi.astype("float32"),lswi.astype("float32"),choice.astype("float32")])

def write_snapshot(path,arr,transform,crs):
    import rasterio
    profile={"driver":"GTiff","width":arr.shape[2],"height":arr.shape[1],"count":arr.shape[0],
             "dtype":"float32","crs":crs,"transform":transform,"compress":"DEFLATE","predictor":3,
             "tiled":True,"blockxsize":256,"blockysize":256}
    with rasterio.open(path,"w",**profile) as ds:
        ds.write(arr)
        for i,n in enumerate(SNAPSHOT_BANDS,1): ds.set_band_description(i,n)

def qa_png(path,arr):
    from PIL import Image
    rgb=np.stack([arr[2],arr[1],arr[0]],axis=2)
    rgb=np.clip(rgb*3.0,0,1)
    img=(rgb*255).astype(np.uint8)
    bad=arr[7]<0.5
    img[bad]=((0.35*img[bad])+(0.65*np.array([255,40,80]))).astype(np.uint8)
    Image.fromarray(img).save(path)

def main():
    import geopandas as gpd, pandas as pd, rasterio
    from rasterio.features import rasterize

    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    master=json.loads(MASTER.read_text(encoding="utf-8"))
    cfg=json.loads(B1CFG.read_text(encoding="utf-8"))
    pdir=Path(args.pilot_dir or cfg["pilot_selection_dir"])
    out=Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True,exist_ok=True)
    pilot_path=pdir/"pilot_fields_2025.gpkg"
    if not pilot_path.exists(): raise FileNotFoundError(pilot_path)
    g=gpd.read_file(pilot_path).to_crs(32633)
    if len(g)!=221: raise RuntimeError(f"Expected frozen B0 pilot of 221 fields, got {len(g)}")
    bbox=aligned_bounds(g.total_bounds,cfg["resolution_m"],cfg["buffer_m"])
    width=int(round((bbox[2]-bbox[0])/cfg["resolution_m"])); height=int(round((bbox[3]-bbox[1])/cfg["resolution_m"]))
    if width>cfg["maximum_width_pixels"] or height>cfg["maximum_height_pixels"]:
        raise RuntimeError(f"Raster guard exceeded: {width}x{height}")

    print(f"GRID={width}x{height} BBOX_32633={[round(x,1) for x in bbox]}")
    tok=oauth(master); reported=0.0; request_rows=[]
    source_arrays={}; transform=None; crs=None
    for snap,days in master["snapshots"].items():
        source_arrays[snap]=[]
        for day in days:
            f=out/"source_daily"/f"s2_{day}.tif"
            m,hit=fetch_tiff(tok,payload(day,bbox,width,height),f)
            if m.get("reported_pu") is not None and not hit: reported+=float(m["reported_pu"])
            request_rows.append({"snapshot":snap,"date":day,"cache_hit":hit,"reported_pu":m.get("reported_pu"),"bytes":m["bytes"]})
            arr,tr,cc=read_source(f,width,height); source_arrays[snap].append(arr)
            if transform is None: transform,crs=tr,cc
            elif tr!=transform or cc!=crs: raise RuntimeError("Source raster grid mismatch")

    if reported>cfg["maximum_total_reported_pu"]: raise RuntimeError(f"PU guard exceeded: {reported}")

    snapshots={}
    for snap,arrays in source_arrays.items():
        arr=choose_pair(arrays,set(cfg["clear_scl_codes"]))
        snapshots[snap]=arr
        f=out/f"{snap.lower()}.tif"; write_snapshot(f,arr,transform,crs); qa_png(out/f"{snap.lower()}_qa.png",arr)

    # Rasterize field IDs once and compute per-field VALID fractions for all four snapshots.
    shapes=[(geom,i+1) for i,geom in enumerate(g.geometry)]
    labels=rasterize(shapes,out_shape=(height,width),transform=transform,fill=0,dtype="int32",all_touched=False)
    totals=np.bincount(labels.ravel(),minlength=len(g)+1).astype(float)
    rows=[]
    ids=g["parent_field_id_2025"].astype(str).tolist()
    for i,fid in enumerate(ids,1):
        r={"parent_field_id_2025":fid,"pixels":int(totals[i])}
        for snap,arr in snapshots.items():
            good=np.bincount(labels.ravel(),weights=arr[7].ravel(),minlength=len(g)+1)
            r[f"valid_{snap.lower()}"]=None if totals[i]==0 else round(float(good[i]/totals[i]),6)
        rows.append(r)
    pd.DataFrame(rows).to_csv(out/"field_snapshot_validity.csv",index=False)
    pd.DataFrame(request_rows).to_csv(out/"api_requests.csv",index=False)

    summary=[]
    for snap,arr in snapshots.items():
        mask=labels>0; vf=float(arr[7][mask].mean()) if mask.any() else 0.0
        vals=[r[f"valid_{snap.lower()}"] for r in rows if r[f"valid_{snap.lower()}"] is not None]
        summary.append({"snapshot":snap,"pilot_pixel_valid_fraction":round(vf,6),
                        "fields_ge_0p8_valid":sum(v>=0.8 for v in vals),
                        "fields_ge_0p5_valid":sum(v>=0.5 for v in vals),
                        "fields_total":len(vals)})
    manifest={"schema_version":"akerpuls-prelim-fields-2026-b1-v1","status":"PASS",
              "grid":{"bbox_32633":[float(x) for x in bbox],"width":width,"height":height,"resolution_m":cfg["resolution_m"]},
              "pilot_fields":len(g),"snapshot_dates":master["snapshots"],"pair_rule":cfg["pair_rule"],
              "new_reported_pu_total":round(reported,6),"snapshot_validity":summary,
              "outputs":["s2_2026_april.tif","s2_2026_may.tif","s2_2026_june.tif","s2_2026_july.tif","field_snapshot_validity.csv"],
              "next_step":"STOPPUNKT B2 split/merge baseline; no crop classification"}
    (out/"b1_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"NEW_REPORTED_PU_TOTAL={reported:.6f}")
    for s in summary:
        print(f'{s["snapshot"]}: VALID_PIXELS={s["pilot_pixel_valid_fraction"]:.4f} FIELDS_GE80={s["fields_ge_0p8_valid"]}/{s["fields_total"]} FIELDS_GE50={s["fields_ge_0p5_valid"]}/{s["fields_total"]}')
    print("B1_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__": raise SystemExit(main())
