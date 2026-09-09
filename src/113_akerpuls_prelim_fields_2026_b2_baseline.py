#!/usr/bin/env python3
"""STOPPUNKT B2: conservative local split/merge baseline for the 221-field pilot. Zero API calls."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b2.json"
SNAPS=["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]

def rms(v): return float(np.sqrt(np.mean(np.square(v)))) if np.size(v) else 0.0

def deterministic_k2(x, max_iter=30):
    if len(x)<2: return None
    xc=x-x.mean(axis=0,keepdims=True)
    try:
        _,_,vt=np.linalg.svd(xc,full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    p=xc@vt[0]
    if float(np.nanmax(p)-np.nanmin(p))<1e-8: return None
    q1,q3=np.quantile(p,[0.20,0.80])
    c=np.stack([x[int(np.argmin(np.abs(p-q1)))],x[int(np.argmin(np.abs(p-q3)))]]).astype(float)
    lab=np.zeros(len(x),dtype=np.int8)
    for _ in range(max_iter):
        d0=np.sum((x-c[0])**2,axis=1); d1=np.sum((x-c[1])**2,axis=1)
        new=(d1<d0).astype(np.int8)
        if new.min()==new.max(): return None
        nc=np.stack([x[new==0].mean(axis=0),x[new==1].mean(axis=0)])
        if np.array_equal(new,lab) and np.max(np.abs(nc-c))<1e-7:
            lab=new; c=nc; break
        lab=new; c=nc
    resid=np.sqrt(np.sum((x-c[lab])**2,axis=1)/x.shape[1])
    within=float(np.sqrt(np.mean(resid**2)))
    between=rms(c[0]-c[1])
    return lab,c,between,within

def largest_component(mask, ndi):
    labs,n=ndi.label(mask,structure=np.ones((3,3),dtype=np.uint8))
    if n==0: return np.zeros_like(mask,dtype=bool),0
    counts=np.bincount(labs.ravel()); counts[0]=0; k=int(np.argmax(counts))
    return labs==k,int(counts[k])

def mask_geom(mask, transform, parent_geom):
    from rasterio.features import shapes
    from shapely.geometry import shape
    from shapely.ops import unary_union
    geoms=[shape(g) for g,v in shapes(mask.astype(np.uint8),mask=mask,transform=transform) if int(v)==1]
    if not geoms: return None
    g=unary_union(geoms).intersection(parent_geom)
    return None if g.is_empty else g

def load_snapshots(raster_dir, feature_names):
    import rasterio
    cubes=[]; valids=[]; rgb=[]; transform=None; crs=None; shape_hw=None
    for snap in SNAPS:
        p=raster_dir/f"{snap.lower()}.tif"
        if not p.exists(): raise FileNotFoundError(p)
        with rasterio.open(p) as ds:
            desc=list(ds.descriptions)
            idx={n:i+1 for i,n in enumerate(desc) if n}
            missing=[n for n in feature_names+["VALID"] if n not in idx]
            if missing: raise RuntimeError(f"{p.name}: missing bands {missing}")
            arr=np.stack([ds.read(idx[n]).astype(np.float32) for n in feature_names])
            valid=ds.read(idx["VALID"])>0.5
            rr=np.stack([ds.read(idx["B04"]),ds.read(idx["B03"]),ds.read(idx["B02"])])
            if transform is None:
                transform,crs,shape_hw=ds.transform,ds.crs,(ds.height,ds.width)
            elif ds.transform!=transform or ds.crs!=crs or (ds.height,ds.width)!=shape_hw:
                raise RuntimeError("B1 grids differ")
        cubes.append(arr); valids.append(valid); rgb.append(rr)
    return cubes,valids,rgb,transform,crs,shape_hw

def main():
    import geopandas as gpd, pandas as pd, rasterio
    from scipy import ndimage as ndi
    from rasterio.features import rasterize
    from shapely.geometry import LineString

    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    pdir=Path(args.pilot_dir or cfg["pilot_dir"]); rdir=Path(args.raster_dir or cfg["raster_dir"]); out=Path(args.output_dir or cfg["output_dir"])
    out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((rdir/"b1_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status")!="PASS" or int(manifest.get("pilot_fields",0))!=221:
        raise RuntimeError("Accepted B1 manifest is missing or mismatched")

    g=gpd.read_file(pdir/"pilot_fields_2025.gpkg").to_crs(32633).reset_index(drop=True)
    adj=pd.read_csv(pdir/"pilot_adjacency.csv",dtype={"field_a":str,"field_b":str})
    features=list(cfg["feature_bands_per_snapshot"])
    cubes,valids,rgbs,transform,crs,(h,w)=load_snapshots(rdir,features)

    ids=g["parent_field_id_2025"].astype(str).tolist()
    id_to_pos={fid:i for i,fid in enumerate(ids)}
    labels=rasterize([(geom,i+1) for i,geom in enumerate(g.geometry)],out_shape=(h,w),transform=transform,fill=0,dtype="int32",all_touched=False)
    all_valid=np.logical_and.reduce(valids)

    # Robust global scaling from valid pilot pixels.
    raw=np.concatenate(cubes,axis=0).transpose(1,2,0)
    pilotmask=(labels>0)&all_valid
    sample=raw[pilotmask]
    center=np.nanmedian(sample,axis=0)
    mad=np.nanmedian(np.abs(sample-center),axis=0)*1.4826
    std=np.nanstd(sample,axis=0)
    scale=np.where(mad>1e-6,mad,np.where(std>1e-6,std,1.0))
    z=(raw-center)/scale
    dims_per=len(features)

    split_rows=[]; child_rows=[]; field_stats={}
    sp=cfg["split"]
    for pos,row in g.iterrows():
        fid=str(row["parent_field_id_2025"]); fm=labels==(pos+1)
        interior=ndi.binary_erosion(fm,structure=np.ones((3,3),dtype=bool),iterations=int(sp["interior_erosion_pixels"]),border_value=0)
        if interior.sum()<int(sp["minimum_valid_pixels"]): interior=fm.copy()
        m=interior&all_valid
        n=int(m.sum()); total=int(fm.sum())
        valid_fraction=n/max(1,int(interior.sum()))
        if n<int(sp["minimum_valid_pixels"]):
            split_rows.append({"parent_field_id_2025":fid,"change_type":"UNCERTAIN","confidence":0.0,"reason":"TOO_FEW_ALL_VALID_INTERIOR_PIXELS","pixels":total,"analysis_pixels":n})
            continue
        x=z[m]
        mean=x.mean(axis=0); within=rms(x-mean)
        field_stats[fid]={"mean":mean,"within":within,"mask":fm}
        fit=deterministic_k2(x)
        if fit is None:
            split_rows.append({"parent_field_id_2025":fid,"change_type":"UNCHANGED","confidence":0.75,"reason":"NO_STABLE_K2","pixels":total,"analysis_pixels":n})
            continue
        lab,c,between,win=fit
        sep_ratio=between/max(win,0.15)

        # Put labels back in raster coordinates and assess connectedness.
        cluster_img=np.full((h,w),-1,dtype=np.int8); cluster_img[m]=lab
        comps=[]; comp_counts=[]
        for k in (0,1):
            cm,count=largest_component(cluster_img==k,ndi); comps.append(cm); comp_counts.append(count)
        coherence=sum(comp_counts)/max(1,n)
        fractions=[c/max(1,n) for c in comp_counts]
        minfrac=min(fractions); minpix=min(comp_counts)

        support=0; snap_ratios=[]
        for sidx in range(4):
            sl=slice(sidx*dims_per,(sidx+1)*dims_per)
            d=rms(c[0,sl]-c[1,sl])
            xx=x[:,sl]; rr=np.sqrt(np.mean((xx-c[lab][:,sl])**2,axis=1))
            ww=float(np.sqrt(np.mean(rr**2)))
            ratio=d/max(ww,0.15); snap_ratios.append(ratio)
            support += int(ratio>=float(sp["snapshot_support_ratio"]))

        score=(0.30*min(1.0,max(0.0,(sep_ratio-1.0)/1.5))
               +0.25*(support/4.0)
               +0.25*min(1.0,coherence)
               +0.20*min(1.0,minfrac/0.30))
        is_split=(minpix>=int(sp["minimum_child_pixels"]) and
                  minfrac>=float(sp["minimum_child_fraction"]) and
                  coherence>=float(sp["minimum_spatial_coherence"]) and
                  sep_ratio>=float(sp["minimum_total_separation_ratio"]) and
                  support>=int(sp["minimum_supporting_snapshots"]))
        ctype="SPLIT" if is_split else "UNCHANGED"
        conf=float(np.clip(score if is_split else 0.55+0.35*(1-score),0,0.99))
        split_rows.append({
            "parent_field_id_2025":fid,"change_type":ctype,"confidence":round(conf,4),"reason":"K2_BASELINE",
            "pixels":total,"analysis_pixels":n,"all_valid_fraction":round(valid_fraction,4),
            "separation_ratio":round(sep_ratio,4),"spatial_coherence":round(coherence,4),
            "min_child_fraction":round(minfrac,4),"min_child_pixels":int(minpix),
            "supporting_snapshots":int(support),
            "sep_april":round(snap_ratios[0],4),"sep_may":round(snap_ratios[1],4),
            "sep_june":round(snap_ratios[2],4),"sep_july":round(snap_ratios[3],4)
        })
        if is_split:
            # Largest component of each cluster only; conservative child polygons for QA.
            for k,cm in enumerate(comps):
                geom=mask_geom(cm,transform,row.geometry)
                if geom is not None:
                    child_rows.append({
                      "candidate_field_id_2026":f"{fid}::S{k+1}",
                      "parent_field_id_2025":fid,"change_type":"SPLIT","confidence":round(conf,4),
                      "cluster":k+1,"pixel_area_ha":round(comp_counts[k]*0.01,4),"geometry":geom
                    })

    split_df=pd.DataFrame(split_rows)
    # Ensure field stats exist also for rare uncertain fields, using valid full-field pixels where possible.
    for pos,row in g.iterrows():
        fid=str(row["parent_field_id_2025"])
        if fid in field_stats: continue
        m=(labels==(pos+1))&all_valid
        if m.sum()>=4:
            x=z[m]; mu=x.mean(axis=0); field_stats[fid]={"mean":mu,"within":rms(x-mu),"mask":labels==(pos+1)}

    mg=cfg["merge"]; merge_rows=[]; merge_geoms=[]
    for pair in adj.itertuples(index=False):
        a=str(pair.field_a); b=str(pair.field_b)
        if a not in id_to_pos or b not in id_to_pos or a not in field_stats or b not in field_stats: continue
        ia=id_to_pos[a]; ib=id_to_pos[b]
        ma=labels==(ia+1); mb=labels==(ib+1)
        strip_a=ma & ndi.binary_dilation(mb,iterations=int(mg["boundary_dilation_pixels"]),structure=np.ones((3,3),dtype=bool))
        strip_b=mb & ndi.binary_dilation(ma,iterations=int(mg["boundary_dilation_pixels"]),structure=np.ones((3,3),dtype=bool))
        boundary=[]; valid_snaps=0; strong=0
        for sidx in range(4):
            va=strip_a&valids[sidx]; vb=strip_b&valids[sidx]
            if va.sum()<int(mg["minimum_strip_pixels_per_side"]) or vb.sum()<int(mg["minimum_strip_pixels_per_side"]):
                boundary.append(None); continue
            sl=slice(sidx*dims_per,(sidx+1)*dims_per)
            da=rms(z[va][:,sl].mean(axis=0)-z[vb][:,sl].mean(axis=0))
            boundary.append(da); valid_snaps+=1; strong+=int(da>=float(mg["strong_edge_distance"]))

        fs_a=field_stats[a]; fs_b=field_stats[b]
        field_dist=rms(fs_a["mean"]-fs_b["mean"])
        pooled=0.5*(float(fs_a["within"])+float(fs_b["within"]))
        bw_ratio=field_dist/max(pooled,0.15)
        vals=[x for x in boundary if x is not None]
        bmed=float(np.median(vals)) if vals else None
        sim_field=math.exp(-field_dist)
        sim_boundary=math.exp(-bmed) if bmed is not None else 0.0
        stability=(valid_snaps/4.0)*(1.0-strong/4.0)
        conf=0.45*sim_field+0.40*sim_boundary+0.15*stability
        cand=(valid_snaps>=int(mg["minimum_valid_boundary_snapshots"]) and
              field_dist<=float(mg["maximum_field_mean_distance"]) and
              bw_ratio<=float(mg["maximum_between_within_ratio"]) and
              bmed is not None and bmed<=float(mg["maximum_boundary_median_distance"]) and
              strong<=int(mg["maximum_strong_edge_snapshots"]) and conf>=float(mg["minimum_confidence"]))
        merge_rows.append({
          "field_a":a,"field_b":b,"change_type":"MERGE_CANDIDATE" if cand else "KEEP_BOUNDARY",
          "confidence":round(conf,4),"field_mean_distance":round(field_dist,4),
          "between_within_ratio":round(bw_ratio,4),"boundary_median_distance":None if bmed is None else round(bmed,4),
          "valid_boundary_snapshots":valid_snaps,"strong_edge_snapshots":strong,
          "edge_april":None if boundary[0] is None else round(boundary[0],4),
          "edge_may":None if boundary[1] is None else round(boundary[1],4),
          "edge_june":None if boundary[2] is None else round(boundary[2],4),
          "edge_july":None if boundary[3] is None else round(boundary[3],4),
          "shared_boundary_m_2025":float(pair.shared_boundary_m),"distance_m_2025":float(pair.distance_m)
        })
        if cand:
            ca=g.loc[ia].geometry.centroid; cb=g.loc[ib].geometry.centroid
            merge_geoms.append({"field_a":a,"field_b":b,"change_type":"MERGE_CANDIDATE","confidence":round(conf,4),
                                "geometry":LineString([ca,cb])})

    merge_df=pd.DataFrame(merge_rows)
    split_df.to_csv(out/"b2_field_changes.csv",index=False)
    merge_df.to_csv(out/"b2_boundary_changes.csv",index=False)

    # QA vector outputs.
    fields=g[["parent_field_id_2025","area_ha_2025","geometry"]].merge(split_df,on="parent_field_id_2025",how="left")
    fields.to_file(out/"b2_fields_qa.gpkg",layer="field_changes",driver="GPKG")
    if child_rows:
        gpd.GeoDataFrame(child_rows,geometry="geometry",crs=32633).to_file(out/"b2_split_children_qa.gpkg",layer="split_children",driver="GPKG")
    if merge_geoms:
        gpd.GeoDataFrame(merge_geoms,geometry="geometry",crs=32633).to_file(out/"b2_merge_candidates_qa.gpkg",layer="merge_candidates",driver="GPKG")

    nsplit=int((split_df["change_type"]=="SPLIT").sum())
    nunc=int((split_df["change_type"]=="UNCERTAIN").sum())
    nmerge=int((merge_df["change_type"]=="MERGE_CANDIDATE").sum()) if not merge_df.empty else 0
    top_splits=split_df[split_df["change_type"]=="SPLIT"].sort_values("confidence",ascending=False).head(15).to_dict(orient="records")
    top_merges=merge_df[merge_df["change_type"]=="MERGE_CANDIDATE"].sort_values("confidence",ascending=False).head(15).to_dict(orient="records") if not merge_df.empty else []
    summary={
      "schema_version":"akerpuls-prelim-fields-2026-b2-baseline-v1","status":"PASS",
      "pilot_fields":len(g),"adjacency_pairs":len(adj),
      "unchanged":int((split_df["change_type"]=="UNCHANGED").sum()),
      "split_candidates":nsplit,"uncertain":nunc,
      "merge_candidates":nmerge,
      "split_candidate_rate":round(nsplit/len(g),4),
      "merge_candidate_rate":round(nmerge/max(1,len(adj)),4),
      "top_split_candidates":top_splits,"top_merge_candidates":top_merges,
      "sentinel_hub_pu_used":0,
      "interpretation":"Baseline candidates only. No 2025 boundary is modified and no merge is executed.",
      "next_step":"Visual QA plus threshold/leave-one-snapshot robustness before accepting STOPPUNKT B."
    }
    (out/"b2_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT B2 SPLIT/MERGE BASELINE")
    print(f'UNCHANGED={summary["unchanged"]}/{len(g)}')
    print(f'SPLIT_CANDIDATES={nsplit}/{len(g)} RATE={summary["split_candidate_rate"]:.4f}')
    print(f'UNCERTAIN={nunc}/{len(g)}')
    print(f'MERGE_CANDIDATES={nmerge}/{len(adj)} RATE={summary["merge_candidate_rate"]:.4f}')
    if top_splits:
        print("TOP_SPLITS="+",".join(f'{r["parent_field_id_2025"]}:{r["confidence"]}' for r in top_splits[:8]))
    if top_merges:
        print("TOP_MERGES="+",".join(f'{r["field_a"]}+{r["field_b"]}:{r["confidence"]}' for r in top_merges[:8]))
    print("SENTINEL_HUB_PU_USED=0")
    print("B2_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__": raise SystemExit(main())
