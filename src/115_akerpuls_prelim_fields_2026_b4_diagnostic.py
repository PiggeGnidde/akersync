#!/usr/bin/env python3
"""STOPPUNKT B4: morphology/edge sensitivity diagnostic for B2 candidates. Zero API calls."""
from __future__ import annotations
import argparse, itertools, json, math
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b4.json"
B2CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b2.json"
SNAPS=["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]
EDGE_COLS=["edge_april","edge_may","edge_june","edge_july"]

def rms(v):
    return float(np.sqrt(np.mean(np.square(v)))) if np.size(v) else 0.0

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
    return lab,c

def load_snapshots(raster_dir, feature_names):
    import rasterio
    cubes=[]; valids=[]; transform=None; crs=None; shape_hw=None
    for snap in SNAPS:
        p=raster_dir/f"{snap.lower()}.tif"
        if not p.exists(): raise FileNotFoundError(p)
        with rasterio.open(p) as ds:
            idx={n:i+1 for i,n in enumerate(ds.descriptions) if n}
            missing=[n for n in feature_names+["VALID"] if n not in idx]
            if missing: raise RuntimeError(f"{p.name}: missing bands {missing}")
            arr=np.stack([ds.read(idx[n]).astype(np.float32) for n in feature_names])
            valid=ds.read(idx["VALID"])>0.5
            if transform is None:
                transform,crs,shape_hw=ds.transform,ds.crs,(ds.height,ds.width)
            elif ds.transform!=transform or ds.crs!=crs or (ds.height,ds.width)!=shape_hw:
                raise RuntimeError("B1 grids differ")
        cubes.append(arr); valids.append(valid)
    return cubes,valids,transform,crs,shape_hw

def largest_component_fraction(mask, ndi):
    labs,n=ndi.label(mask,structure=np.ones((3,3),dtype=np.uint8))
    total=int(mask.sum())
    if total<=0 or n<=0: return 0.0,0
    counts=np.bincount(labs.ravel()); counts[0]=0
    return float(counts.max()/total), int(n)

def interface_mask(a,b,ndi):
    return (a & ndi.binary_dilation(b,structure=np.ones((3,3),dtype=bool))) | (b & ndi.binary_dilation(a,structure=np.ones((3,3),dtype=bool)))

def morphology_metrics(cluster0,cluster1,interior,parent,ndi,resolution_m):
    perimeter=interior & ~ndi.binary_erosion(interior,structure=np.ones((3,3),dtype=bool),border_value=0)
    c0_boundary=bool((cluster0 & ndi.binary_dilation(perimeter,iterations=1)).any())
    c1_boundary=bool((cluster1 & ndi.binary_dilation(perimeter,iterations=1)).any())

    f0,n0=largest_component_fraction(cluster0,ndi)
    f1,n1=largest_component_fraction(cluster1,ndi)
    iface=interface_mask(cluster0,cluster1,ndi)
    iface_px=int(iface.sum())
    endmask=iface & ndi.binary_dilation(perimeter,iterations=1)
    _,end_components=ndi.label(endmask,structure=np.ones((3,3),dtype=np.uint8))
    endpoints=int(min(end_components,4))
    return {
        "both_children_touch_outer":bool(c0_boundary and c1_boundary),
        "child0_touches_outer":bool(c0_boundary),
        "child1_touches_outer":bool(c1_boundary),
        "child0_largest_component_fraction":round(f0,4),
        "child1_largest_component_fraction":round(f1,4),
        "child0_components":n0,
        "child1_components":n1,
        "interface_pixels":iface_px,
        "interface_length_proxy_m":round(iface_px*float(resolution_m)/2.0,1),
        "interface_outer_endpoint_components":endpoints,
    },iface

def split_edge_metrics(cluster0,cluster1,iface,z,valids,dims_per,ndi,strip_pixels):
    rows=[]
    near=ndi.binary_dilation(iface,iterations=int(strip_pixels),structure=np.ones((3,3),dtype=bool))
    for sidx,snap in enumerate(SNAPS):
        sl=slice(sidx*dims_per,(sidx+1)*dims_per)
        a=cluster0 & near & valids[sidx]
        b=cluster1 & near & valids[sidx]
        if a.sum()<3 or b.sum()<3:
            rows.append((snap,None,None,None))
            continue
        xa=z[a][:,sl]; xb=z[b][:,sl]
        dist=rms(xa.mean(axis=0)-xb.mean(axis=0))
        wa=rms(xa-xa.mean(axis=0)); wb=rms(xb-xb.mean(axis=0))
        ratio=dist/max(0.15,0.5*(wa+wb))
        rows.append((snap,float(dist),float(ratio),int(min(a.sum(),b.sum()))))
    return rows

def anchor_class_map(items):
    out={}
    for cls,vals in items.items():
        for key in vals: out[str(key)]=cls
    return out

def summarize_anchor_rule(keys,passed,anchors,positive_class,negative_class):
    pos=[k for k in keys if anchors.get(k)==positive_class]
    neg=[k for k in keys if anchors.get(k)==negative_class]
    return {
        "anchor_positive_total":len(pos),
        "anchor_positive_retained":sum(bool(passed.get(k,False)) for k in pos),
        "anchor_negative_total":len(neg),
        "anchor_negative_rejected":sum(not bool(passed.get(k,False)) for k in neg),
    }

def main():
    import geopandas as gpd, pandas as pd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize

    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--baseline-dir")
    ap.add_argument("--b3-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    b2cfg=json.loads(B2CFG.read_text(encoding="utf-8"))
    pdir=Path(args.pilot_dir or cfg["pilot_dir"])
    rdir=Path(args.raster_dir or cfg["raster_dir"])
    bdir=Path(args.baseline_dir or cfg["baseline_dir"])
    qdir=Path(args.b3_dir or cfg["b3_dir"])
    out=Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True,exist_ok=True)

    g=gpd.read_file(pdir/"pilot_fields_2025.gpkg").to_crs(32633).reset_index(drop=True)
    fields=pd.read_csv(bdir/"b2_field_changes.csv",dtype={"parent_field_id_2025":str})
    merges=pd.read_csv(bdir/"b2_boundary_changes.csv",dtype={"field_a":str,"field_b":str})
    loo_split=pd.read_csv(qdir/"split_loo_robustness.csv",dtype={"parent_field_id_2025":str})
    loo_merge=pd.read_csv(qdir/"merge_loo_robustness.csv",dtype={"field_a":str,"field_b":str})
    feature_names=list(b2cfg["feature_bands_per_snapshot"])
    cubes,valids,transform,crs,(h,w)=load_snapshots(rdir,feature_names)
    labels=rasterize([(geom,i+1) for i,geom in enumerate(g.geometry)],out_shape=(h,w),transform=transform,fill=0,dtype="int32",all_touched=False)
    all_valid=np.logical_and.reduce(valids)

    raw=np.concatenate(cubes,axis=0).transpose(1,2,0)
    pilotmask=(labels>0)&all_valid
    sample=raw[pilotmask]
    center=np.nanmedian(sample,axis=0)
    mad=np.nanmedian(np.abs(sample-center),axis=0)*1.4826
    std=np.nanstd(sample,axis=0)
    scale=np.where(mad>1e-6,mad,np.where(std>1e-6,std,1.0))
    z=(raw-center)/scale
    dims_per=len(feature_names)
    res=float(abs(transform.a))

    split_base=fields[fields["change_type"]=="SPLIT"].copy()
    split_rows=[]
    sp=b2cfg["split"]
    for rec in split_base.itertuples(index=False):
        fid=str(rec.parent_field_id_2025)
        pos=int(g.index[g["parent_field_id_2025"].astype(str)==fid][0])
        fm=labels==(pos+1)
        interior=ndi.binary_erosion(fm,structure=np.ones((3,3),dtype=bool),iterations=int(sp["interior_erosion_pixels"]),border_value=0)
        if interior.sum()<int(sp["minimum_valid_pixels"]): interior=fm.copy()
        m=interior&all_valid
        x=z[m]
        fit=deterministic_k2(x)
        if fit is None:
            continue
        lab,c=fit
        img=np.full((h,w),-1,dtype=np.int8); img[m]=lab
        c0=img==0; c1=img==1
        morph,iface=morphology_metrics(c0,c1,interior,fm,ndi,res)
        edge=split_edge_metrics(c0,c1,iface,z,valids,dims_per,ndi,cfg["split"]["edge_strip_pixels"])
        row={"parent_field_id_2025":fid,"b2_confidence":float(rec.confidence),**morph}
        for snap,dist,ratio,nmin in edge:
            s=snap.split("_")[-1].lower()
            row[f"edge_{s}"]=None if dist is None else round(dist,4)
            row[f"edge_ratio_{s}"]=None if ratio is None else round(ratio,4)
            row[f"edge_min_strip_pixels_{s}"]=nmin
        ratios=[r[2] for r in edge if r[2] is not None]
        row["edge_ratio_median"]=None if not ratios else round(float(np.median(ratios)),4)
        row["edge_ratio_max"]=None if not ratios else round(float(np.max(ratios)),4)
        row["loo_all4"]=bool(loo_split.loc[loo_split["parent_field_id_2025"]==fid,"loo_all4"].iloc[0]) if (loo_split["parent_field_id_2025"]==fid).any() else False
        split_rows.append(row)
    split_diag=pd.DataFrame(split_rows)

    split_anchors=anchor_class_map(cfg["manual_visual_anchors"]["split"])
    split_diag["manual_anchor_class"]=split_diag["parent_field_id_2025"].map(split_anchors)
    split_rules=[]
    for min_lcf,min_iface,min_end,edge_thr,min_edge_snaps,require_loo in itertools.product(
        cfg["split"]["largest_component_fraction_grid"],
        cfg["split"]["minimum_interface_pixels_grid"],
        cfg["split"]["minimum_endpoint_components_grid"],
        cfg["split"]["edge_ratio_threshold_grid"],
        cfg["split"]["minimum_edge_snapshots_grid"],
        cfg["split"]["require_loo_all4_grid"],
    ):
        passed={}
        for r in split_diag.itertuples(index=False):
            edgevals=[getattr(r,f"edge_ratio_{x}") for x in ("april","may","june","july")]
            edge_count=sum((v is not None and float(v)>=float(edge_thr)) for v in edgevals)
            ok=(bool(r.both_children_touch_outer)
                and float(r.child0_largest_component_fraction)>=float(min_lcf)
                and float(r.child1_largest_component_fraction)>=float(min_lcf)
                and int(r.interface_pixels)>=int(min_iface)
                and int(r.interface_outer_endpoint_components)>=int(min_end)
                and edge_count>=int(min_edge_snaps)
                and ((not require_loo) or bool(r.loo_all4)))
            passed[str(r.parent_field_id_2025)]=ok
        stats=summarize_anchor_rule(split_diag["parent_field_id_2025"].astype(str).tolist(),passed,split_anchors,"CLEAR","FALSE")
        split_rules.append({
            "largest_component_fraction":min_lcf,"minimum_interface_pixels":min_iface,
            "minimum_endpoint_components":min_end,"edge_ratio_threshold":edge_thr,
            "minimum_edge_snapshots":min_edge_snaps,"require_loo_all4":require_loo,
            "retained_candidates":sum(passed.values()),**stats
        })
    split_sens=pd.DataFrame(split_rules)

    merge_base=merges[merges["change_type"]=="MERGE_CANDIDATE"].copy()
    merge_base["pair_key"]=merge_base["field_a"].astype(str)+" + "+merge_base["field_b"].astype(str)
    merge_loo=loo_merge.copy()
    merge_loo["pair_key"]=merge_loo["field_a"].astype(str)+" + "+merge_loo["field_b"].astype(str)
    merge_base=merge_base.merge(merge_loo[["pair_key","loo_all4","loo_pass_count"]],on="pair_key",how="left")
    merge_anchors=anchor_class_map(cfg["manual_visual_anchors"]["merge"])
    merge_base["manual_anchor_class"]=merge_base["pair_key"].map(merge_anchors)
    merge_rules=[]
    for max_field,max_bw,max_med,max_edge,max_strong,require_loo in itertools.product(
        cfg["merge"]["maximum_field_mean_distance_grid"],
        cfg["merge"]["maximum_between_within_ratio_grid"],
        cfg["merge"]["maximum_boundary_median_distance_grid"],
        cfg["merge"]["maximum_single_snapshot_edge_grid"],
        cfg["merge"]["maximum_strong_edge_snapshots_grid"],
        cfg["merge"]["require_loo_all4_grid"],
    ):
        passed={}
        for r in merge_base.itertuples(index=False):
            vals=[getattr(r,c) for c in EDGE_COLS]
            vals=[float(v) for v in vals if v is not None and not (isinstance(v,float) and math.isnan(v))]
            mx=max(vals) if vals else 999.0
            strong=sum(v>=float(cfg["merge"]["strong_edge_distance"]) for v in vals)
            ok=(float(r.field_mean_distance)<=float(max_field)
                and float(r.between_within_ratio)<=float(max_bw)
                and float(r.boundary_median_distance)<=float(max_med)
                and mx<=float(max_edge)
                and strong<=int(max_strong)
                and ((not require_loo) or bool(r.loo_all4)))
            passed[str(r.pair_key)]=ok
        stats=summarize_anchor_rule(merge_base["pair_key"].astype(str).tolist(),passed,merge_anchors,"CLEAR","FALSE")
        merge_rules.append({
            "maximum_field_mean_distance":max_field,"maximum_between_within_ratio":max_bw,
            "maximum_boundary_median_distance":max_med,"maximum_single_snapshot_edge":max_edge,
            "maximum_strong_edge_snapshots":max_strong,"require_loo_all4":require_loo,
            "retained_candidates":sum(passed.values()),**stats
        })
    merge_sens=pd.DataFrame(merge_rules)

    for df in (split_sens,merge_sens):
        df["anchor_hits"]=df["anchor_positive_retained"]+df["anchor_negative_rejected"]
        denom=df["anchor_positive_total"]+df["anchor_negative_total"]
        df["anchor_hit_fraction"]=np.where(denom>0,df["anchor_hits"]/denom,np.nan)
    split_sens=split_sens.sort_values(["anchor_hits","anchor_positive_retained","retained_candidates"],ascending=[False,False,True])
    merge_sens=merge_sens.sort_values(["anchor_hits","anchor_positive_retained","retained_candidates"],ascending=[False,False,True])

    split_diag.to_csv(out/"b4_split_morphology_edge_diagnostics.csv",index=False)
    merge_base.to_csv(out/"b4_merge_candidate_diagnostics.csv",index=False)
    split_sens.to_csv(out/"b4_split_sensitivity_grid.csv",index=False)
    merge_sens.to_csv(out/"b4_merge_sensitivity_grid.csv",index=False)

    best_split=split_sens.iloc[0].to_dict() if len(split_sens) else {}
    best_merge=merge_sens.iloc[0].to_dict() if len(merge_sens) else {}
    summary={
        "schema_version":"akerpuls-prelim-fields-2026-b4-diagnostic-v1",
        "status":"PASS",
        "baseline_split_candidates":int(len(split_diag)),
        "baseline_merge_candidates":int(len(merge_base)),
        "split_morphology_both_touch_outer":int(split_diag["both_children_touch_outer"].sum()) if len(split_diag) else 0,
        "split_loo_all4":int(split_diag["loo_all4"].sum()) if len(split_diag) else 0,
        "manual_split_clear_anchors":sum(v=="CLEAR" for v in split_anchors.values()),
        "manual_split_false_anchors":sum(v=="FALSE" for v in split_anchors.values()),
        "manual_merge_clear_anchors":sum(v=="CLEAR" for v in merge_anchors.values()),
        "manual_merge_false_anchors":sum(v=="FALSE" for v in merge_anchors.values()),
        "best_split_sensitivity_row":best_split,
        "best_merge_sensitivity_row":best_merge,
        "sentinel_hub_pu_used":0,
        "thresholds_frozen":False,
        "geometry_modified":False,
        "warning":"Sensitivity ranking uses preliminary visual anchors from 24 QA PNGs, not ground truth. It is diagnostic and must not be interpreted as accuracy.",
        "next_step":"Inspect B4 retention/rejection of reviewed anchors and selected unreviewed cases before choosing B5 candidate rule."
    }
    (out/"b4_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x: x.item() if hasattr(x,"item") else x)+"\n",encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT B4 MORPHOLOGY/EDGE SENSITIVITY")
    print(f'BASELINE_SPLITS={summary["baseline_split_candidates"]} BOTH_CHILDREN_TOUCH_OUTER={summary["split_morphology_both_touch_outer"]} LOO_ALL4={summary["split_loo_all4"]}')
    print(f'BASELINE_MERGES={summary["baseline_merge_candidates"]}')
    if best_split:
        print("BEST_SPLIT_DIAGNOSTIC="
              f'RETAIN={int(best_split["retained_candidates"])} '
              f'CLEAR={int(best_split["anchor_positive_retained"])}/{int(best_split["anchor_positive_total"])} '
              f'FALSE_REJECT={int(best_split["anchor_negative_rejected"])}/{int(best_split["anchor_negative_total"])} '
              f'LCF={best_split["largest_component_fraction"]} IFACEPX={int(best_split["minimum_interface_pixels"])} '
              f'ENDPTS={int(best_split["minimum_endpoint_components"])} EDGE={best_split["edge_ratio_threshold"]} '
              f'EDGESNAPS={int(best_split["minimum_edge_snapshots"])} LOO={bool(best_split["require_loo_all4"])}')
    if best_merge:
        print("BEST_MERGE_DIAGNOSTIC="
              f'RETAIN={int(best_merge["retained_candidates"])} '
              f'CLEAR={int(best_merge["anchor_positive_retained"])}/{int(best_merge["anchor_positive_total"])} '
              f'FALSE_REJECT={int(best_merge["anchor_negative_rejected"])}/{int(best_merge["anchor_negative_total"])} '
              f'FIELD={best_merge["maximum_field_mean_distance"]} BW={best_merge["maximum_between_within_ratio"]} '
              f'MED={best_merge["maximum_boundary_median_distance"]} MAXEDGE={best_merge["maximum_single_snapshot_edge"]} '
              f'STRONG={int(best_merge["maximum_strong_edge_snapshots"])} LOO={bool(best_merge["require_loo_all4"])}')
    print("SENTINEL_HUB_PU_USED=0")
    print("THRESHOLDS_FROZEN=FALSE")
    print("B4_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
