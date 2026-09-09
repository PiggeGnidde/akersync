#!/usr/bin/env python3
"""STOPPUNKT B3: visual QA + leave-one-snapshot-out diagnostics. Zero API calls."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b3.json"
SNAPS=["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]
EDGE_COLS=["edge_april","edge_may","edge_june","edge_july"]
SEP_COLS=["sep_april","sep_may","sep_june","sep_july"]

def split_loo_pass(row,cfg):
    out=[]
    vals=[float(row[c]) for c in SEP_COLS]
    for omit in range(4):
        rem=[v for i,v in enumerate(vals) if i!=omit]
        support=sum(v>=float(cfg["snapshot_support_ratio"]) for v in rem)
        med=float(np.median(rem))
        out.append(bool(support>=int(cfg["minimum_supporting_remaining_snapshots"]) and med>=float(cfg["minimum_remaining_median_ratio"])))
    return out

def merge_loo_pass(row,cfg):
    vals=[]
    for c in EDGE_COLS:
        v=row[c]
        vals.append(None if v is None or (isinstance(v,float) and math.isnan(v)) else float(v))
    out=[]
    for omit in range(4):
        rem=[v for i,v in enumerate(vals) if i!=omit and v is not None]
        valid=len(rem)
        med=float(np.median(rem)) if rem else 999.0
        strong=sum(v>=float(cfg["strong_edge_distance"]) for v in rem)
        out.append(bool(valid>=int(cfg["minimum_valid_remaining_snapshots"]) and
                        med<=float(cfg["maximum_boundary_median_distance"]) and
                        strong<=int(cfg["maximum_strong_edge_remaining_snapshots"])))
    return out

def stretch_rgb(arr):
    x=np.transpose(arr,(1,2,0)).astype(np.float32)
    good=np.isfinite(x).all(axis=2)
    if good.any():
        lo=np.nanpercentile(x[good],2,axis=0); hi=np.nanpercentile(x[good],98,axis=0)
    else:
        lo=np.array([0,0,0],dtype=float); hi=np.array([1,1,1],dtype=float)
    y=(x-lo)/(hi-lo+1e-6)
    return (np.clip(y,0,1)*255).astype(np.uint8)

def bounds_to_window(bounds, transform, width, height, pad_px=3):
    import rasterio.windows
    w=rasterio.windows.from_bounds(*bounds,transform=transform)
    r0=max(0,int(math.floor(w.row_off))-pad_px); c0=max(0,int(math.floor(w.col_off))-pad_px)
    r1=min(height,int(math.ceil(w.row_off+w.height))+pad_px); c1=min(width,int(math.ceil(w.col_off+w.width))+pad_px)
    return rasterio.windows.Window(c0,r0,max(1,c1-c0),max(1,r1-r0))

def overlay_geom(img, geoms, window, transform, value):
    from rasterio.features import rasterize
    import rasterio.windows
    wt=rasterio.windows.transform(window,transform)
    shapes=[]
    for g in geoms:
        if g is None or g.is_empty: continue
        shapes.append((g.boundary.buffer(2.5),1))
    if not shapes: return img
    mask=rasterize(shapes,out_shape=(img.shape[0],img.shape[1]),transform=wt,fill=0,dtype="uint8",all_touched=True)>0
    img=img.copy(); img[mask]=np.array(value,dtype=np.uint8)
    return img

def render_candidate(kind, record, pilot, split_children, raster_paths, out_file):
    import rasterio
    from PIL import Image, ImageOps, ImageDraw

    if kind=="split":
        fid=str(record["parent_field_id_2025"])
        parent=pilot[pilot["parent_field_id_2025"].astype(str)==fid]
        if parent.empty: return False
        geom=parent.geometry.iloc[0]
        children=split_children[split_children["parent_field_id_2025"].astype(str)==fid] if split_children is not None else None
        child_geoms=[] if children is None else list(children.geometry)
        bounds=geom.buffer(80).bounds
        title=f"SPLIT {fid} conf={record['confidence']:.3f}"
    else:
        a=str(record["field_a"]); b=str(record["field_b"])
        ga=pilot[pilot["parent_field_id_2025"].astype(str)==a]
        gb=pilot[pilot["parent_field_id_2025"].astype(str)==b]
        if ga.empty or gb.empty: return False
        geom=ga.geometry.iloc[0].union(gb.geometry.iloc[0])
        child_geoms=[ga.geometry.iloc[0],gb.geometry.iloc[0]]
        bounds=geom.buffer(80).bounds
        title=f"MERGE {a} + {b} conf={record['confidence']:.3f}"

    panels=[]
    for snap,path in raster_paths:
        with rasterio.open(path) as ds:
            win=bounds_to_window(bounds,ds.transform,ds.width,ds.height,pad_px=3)
            idx={n:i+1 for i,n in enumerate(ds.descriptions) if n}
            rgb=np.stack([ds.read(idx["B04"],window=win),ds.read(idx["B03"],window=win),ds.read(idx["B02"],window=win)])
            img=stretch_rgb(rgb)
            img=overlay_geom(img,[geom],win,ds.transform,[255,255,255])
            if child_geoms:
                img=overlay_geom(img,child_geoms,win,ds.transform,[0,0,0])
            im=Image.fromarray(img).resize((280,280))
            canvas=Image.new("RGB",(280,305),"white"); canvas.paste(im,(0,25))
            d=ImageDraw.Draw(canvas); d.text((5,5),snap,fill="black")
            panels.append(canvas)
    sheet=Image.new("RGB",(280*4,340),"white")
    for i,p in enumerate(panels): sheet.paste(p,(i*280,35))
    d=ImageDraw.Draw(sheet); d.text((5,8),title,fill="black")
    sheet.save(out_file)
    return True

def main():
    import geopandas as gpd, pandas as pd

    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--baseline-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()
    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    pdir=Path(args.pilot_dir or cfg["pilot_dir"]); rdir=Path(args.raster_dir or cfg["raster_dir"]); bdir=Path(args.baseline_dir or cfg["baseline_dir"]); out=Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True,exist_ok=True); (out/"splits").mkdir(exist_ok=True); (out/"merges").mkdir(exist_ok=True)

    pilot=gpd.read_file(pdir/"pilot_fields_2025.gpkg").to_crs(32633)
    fields=pd.read_csv(bdir/"b2_field_changes.csv",dtype={"parent_field_id_2025":str})
    bounds=pd.read_csv(bdir/"b2_boundary_changes.csv",dtype={"field_a":str,"field_b":str})
    split_path=bdir/"b2_split_children_qa.gpkg"
    split_children=gpd.read_file(split_path).to_crs(32633) if split_path.exists() else None

    splitcand=fields[fields["change_type"]=="SPLIT"].copy()
    for i,row in splitcand.iterrows():
        loo=split_loo_pass(row,cfg["split_loo"])
        splitcand.loc[i,"loo_pass_count"]=sum(loo)
        splitcand.loc[i,"loo_all4"]=all(loo)
        for j,s in enumerate(SNAPS): splitcand.loc[i,f"omit_{s.lower()}_pass"]=loo[j]
    mergecand=bounds[bounds["change_type"]=="MERGE_CANDIDATE"].copy()
    for i,row in mergecand.iterrows():
        loo=merge_loo_pass(row,cfg["merge_loo"])
        mergecand.loc[i,"loo_pass_count"]=sum(loo)
        mergecand.loc[i,"loo_all4"]=all(loo)
        for j,s in enumerate(SNAPS): mergecand.loc[i,f"omit_{s.lower()}_pass"]=loo[j]

    splitcand=splitcand.sort_values(["loo_all4","loo_pass_count","confidence"],ascending=[False,False,False])
    mergecand=mergecand.sort_values(["loo_all4","loo_pass_count","confidence"],ascending=[False,False,False])
    splitcand.to_csv(out/"split_loo_robustness.csv",index=False)
    mergecand.to_csv(out/"merge_loo_robustness.csv",index=False)

    rasters=[(s,rdir/f"{s.lower()}.tif") for s in SNAPS]
    split_files=[]
    for rank,(_,r) in enumerate(splitcand.head(int(cfg["top_split_images"])).iterrows(),1):
        f=out/"splits"/f"{rank:02d}_{str(r['parent_field_id_2025']).replace('|','_')}.png"
        if render_candidate("split",r,pilot,split_children,rasters,f): split_files.append(str(f))
    merge_files=[]
    for rank,(_,r) in enumerate(mergecand.head(int(cfg["top_merge_images"])).iterrows(),1):
        f=out/"merges"/f"{rank:02d}_{str(r['field_a']).replace('|','_')}__{str(r['field_b']).replace('|','_')}.png"
        if render_candidate("merge",r,pilot,split_children,rasters,f): merge_files.append(str(f))

    summary={
      "schema_version":"akerpuls-prelim-fields-2026-b3-qa-v1","status":"PASS",
      "split_candidates":int(len(splitcand)),
      "split_loo_all4":int(splitcand["loo_all4"].sum()) if len(splitcand) else 0,
      "split_loo_ge3of4":int((splitcand["loo_pass_count"]>=3).sum()) if len(splitcand) else 0,
      "merge_candidates":int(len(mergecand)),
      "merge_loo_all4":int(mergecand["loo_all4"].sum()) if len(mergecand) else 0,
      "merge_loo_ge3of4":int((mergecand["loo_pass_count"]>=3).sum()) if len(mergecand) else 0,
      "split_images":len(split_files),"merge_images":len(merge_files),
      "sentinel_hub_pu_used":0,
      "thresholds_changed":False,
      "interpretation":"LOO is diagnostic only; no threshold tuning or geometry edits performed."
    }
    (out/"b3_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT B3 VISUAL + LOO QA")
    print(f'SPLIT_CANDIDATES={summary["split_candidates"]} LOO_ALL4={summary["split_loo_all4"]} LOO_GE3OF4={summary["split_loo_ge3of4"]}')
    print(f'MERGE_CANDIDATES={summary["merge_candidates"]} LOO_ALL4={summary["merge_loo_all4"]} LOO_GE3OF4={summary["merge_loo_ge3of4"]}')
    print(f'SPLIT_QA_IMAGES={summary["split_images"]}')
    print(f'MERGE_QA_IMAGES={summary["merge_images"]}')
    print("SENTINEL_HUB_PU_USED=0")
    print("B3_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
