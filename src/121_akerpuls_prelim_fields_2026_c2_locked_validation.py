#!/usr/bin/env python3
"""STOPPUNKT C2: independent validation of B2 discovery + locked split rule. Zero API calls."""
from __future__ import annotations

import argparse, importlib.util, json, math
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_c2.json"
C1CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_c1.json"
B2CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b2.json"
B2SCRIPT=ROOT/"src"/"113_akerpuls_prelim_fields_2026_b2_baseline.py"
B4SCRIPT=ROOT/"src"/"115_akerpuls_prelim_fields_2026_b4_diagnostic.py"
B3SCRIPT=ROOT/"src"/"114_akerpuls_prelim_fields_2026_b3_qa.py"
SNAPS=["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]


def load_module(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    import geopandas as gpd
    import pandas as pd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize
    from shapely.geometry import LineString

    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    c1cfg=json.loads(C1CFG.read_text(encoding="utf-8"))
    b2cfg=json.loads(B2CFG.read_text(encoding="utf-8"))
    b2=load_module(B2SCRIPT,"akerpuls_b2_ref")
    b4=load_module(B4SCRIPT,"akerpuls_b4_ref")
    b3=load_module(B3SCRIPT,"akerpuls_b3_ref")

    pdir=Path(args.pilot_dir or cfg["pilot_dir"])
    rdir=Path(args.raster_dir or cfg["raster_dir"])
    out=Path(args.output_dir or cfg["output_dir"]); out.mkdir(parents=True,exist_ok=True)

    manifest=json.loads((rdir/"c1_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status")!="PASS":
        raise RuntimeError("C1 manifest is not PASS")
    if int(manifest.get("pilot_fields",0))!=int(cfg["expected_pilot_fields"]):
        raise RuntimeError("C1 pilot size mismatch")
    if manifest.get("preprocessing_contract")!="IDENTICAL_TO_B1":
        raise RuntimeError("C1 preprocessing contract mismatch")
    if cfg["candidate_discovery_contract"]!="IDENTICAL_TO_B2":
        raise RuntimeError("C2 discovery contract must remain IDENTICAL_TO_B2")
    if cfg["locked_split_rule"]!=c1cfg["locked_split_rule"]:
        raise RuntimeError("C2 locked split rule differs from C1")

    g=gpd.read_file(pdir/"c0_pilot_fields_2025.gpkg").to_crs(32633).reset_index(drop=True)
    if len(g)!=int(cfg["expected_pilot_fields"]):
        raise RuntimeError(f"Expected {cfg['expected_pilot_fields']} C fields, got {len(g)}")
    features=list(b2cfg["feature_bands_per_snapshot"])
    cubes,valids,_rgbs,transform,crs,(h,w)=b2.load_snapshots(rdir,features)

    ids=g["parent_field_id_2025"].astype(str).tolist()
    id_to_pos={fid:i for i,fid in enumerate(ids)}
    labels=rasterize([(geom,i+1) for i,geom in enumerate(g.geometry)],out_shape=(h,w),transform=transform,fill=0,dtype="int32",all_touched=False)
    all_valid=np.logical_and.reduce(valids)

    raw=np.concatenate(cubes,axis=0).transpose(1,2,0)
    pilotmask=(labels>0)&all_valid
    sample=raw[pilotmask]
    if len(sample)==0:
        raise RuntimeError("No all-valid C pixels")
    center=np.nanmedian(sample,axis=0)
    mad=np.nanmedian(np.abs(sample-center),axis=0)*1.4826
    std=np.nanstd(sample,axis=0)
    scale=np.where(mad>1e-6,mad,np.where(std>1e-6,std,1.0))
    z=(raw-center)/scale
    dims_per=len(features)

    sp=b2cfg["split"]
    locked=cfg["locked_split_rule"]
    field_rows=[]; child_rows=[]; field_stats={}

    for pos,row in g.iterrows():
        fid=str(row["parent_field_id_2025"])
        fm=labels==(pos+1)
        interior=ndi.binary_erosion(fm,structure=np.ones((3,3),dtype=bool),iterations=int(sp["interior_erosion_pixels"]),border_value=0)
        if interior.sum()<int(sp["minimum_valid_pixels"]):
            interior=fm.copy()
        m=interior&all_valid
        n=int(m.sum()); total=int(fm.sum())
        if n<int(sp["minimum_valid_pixels"]):
            field_rows.append({"parent_field_id_2025":fid,"discovery_type":"UNCERTAIN","locked_split_pass":False,"reason":"TOO_FEW_ALL_VALID_INTERIOR_PIXELS","pixels":total,"analysis_pixels":n})
            continue

        x=z[m]
        mu=x.mean(axis=0); field_stats[fid]={"mean":mu,"within":b2.rms(x-mu),"mask":fm}
        fit=b2.deterministic_k2(x)
        if fit is None:
            field_rows.append({"parent_field_id_2025":fid,"discovery_type":"UNCHANGED","locked_split_pass":False,"reason":"NO_STABLE_K2","pixels":total,"analysis_pixels":n})
            continue
        lab,c,between,win=fit
        sep_ratio=between/max(win,0.15)
        cluster_img=np.full((h,w),-1,dtype=np.int8); cluster_img[m]=lab
        comps=[]; comp_counts=[]
        for k in (0,1):
            cm,count=b2.largest_component(cluster_img==k,ndi); comps.append(cm); comp_counts.append(count)
        coherence=sum(comp_counts)/max(1,n)
        fractions=[cc/max(1,n) for cc in comp_counts]
        minfrac=min(fractions); minpix=min(comp_counts)

        support=0; snap_ratios=[]
        for sidx in range(4):
            sl=slice(sidx*dims_per,(sidx+1)*dims_per)
            d=b2.rms(c[0,sl]-c[1,sl])
            xx=x[:,sl]; rr=np.sqrt(np.mean((xx-c[lab][:,sl])**2,axis=1))
            ww=float(np.sqrt(np.mean(rr**2)))
            ratio=d/max(ww,0.15); snap_ratios.append(ratio)
            support+=int(ratio>=float(sp["snapshot_support_ratio"]))

        baseline=(minpix>=int(sp["minimum_child_pixels"]) and
                  minfrac>=float(sp["minimum_child_fraction"]) and
                  coherence>=float(sp["minimum_spatial_coherence"]) and
                  sep_ratio>=float(sp["minimum_total_separation_ratio"]) and
                  support>=int(sp["minimum_supporting_snapshots"]))
        if not baseline:
            field_rows.append({
                "parent_field_id_2025":fid,"discovery_type":"UNCHANGED","locked_split_pass":False,"reason":"B2_DISCOVERY_FAIL",
                "pixels":total,"analysis_pixels":n,"separation_ratio":round(sep_ratio,4),"spatial_coherence":round(coherence,4),
                "min_child_fraction":round(minfrac,4),"supporting_snapshots":support,
                "sep_april":round(snap_ratios[0],4),"sep_may":round(snap_ratios[1],4),"sep_june":round(snap_ratios[2],4),"sep_july":round(snap_ratios[3],4)
            })
            continue

        # B4 diagnostics and B5 locked gate, without tuning.
        c0=cluster_img==0; c1=cluster_img==1
        morph,iface=b4.morphology_metrics(c0,c1,interior,fm,ndi,abs(transform.a))
        edge=b4.split_edge_metrics(c0,c1,iface,z,valids,dims_per,ndi,2)
        edge_ratios=[r[2] for r in edge]
        edge_count=sum(v is not None and v>=float(locked["edge_ratio_threshold"]) for v in edge_ratios)
        loo_row={"sep_april":snap_ratios[0],"sep_may":snap_ratios[1],"sep_june":snap_ratios[2],"sep_july":snap_ratios[3]}
        loo=b3.split_loo_pass(loo_row,{"snapshot_support_ratio":1.25,"minimum_supporting_remaining_snapshots":2,"minimum_remaining_median_ratio":1.25})
        loo_all4=all(loo)
        lcf=min(float(morph["child0_largest_component_fraction"]),float(morph["child1_largest_component_fraction"]))
        locked_pass=(lcf>=float(locked["minimum_largest_component_fraction_each_child"]) and
                     edge_count>=int(locked["minimum_supporting_edge_snapshots"]) and
                     ((not bool(locked["require_loo_all4"])) or loo_all4))

        rec={
            "parent_field_id_2025":fid,"discovery_type":"SPLIT_CANDIDATE","locked_split_pass":bool(locked_pass),
            "reason":"LOCKED_RULE_PASS" if locked_pass else "LOCKED_RULE_REJECT",
            "pixels":total,"analysis_pixels":n,"separation_ratio":round(sep_ratio,4),"spatial_coherence":round(coherence,4),
            "min_child_fraction":round(minfrac,4),"supporting_snapshots":support,
            "sep_april":round(snap_ratios[0],4),"sep_may":round(snap_ratios[1],4),"sep_june":round(snap_ratios[2],4),"sep_july":round(snap_ratios[3],4),
            "min_largest_component_fraction":round(lcf,4),"edge_support_count":int(edge_count),"loo_all4":bool(loo_all4),
            "edge_ratio_april":None if edge_ratios[0] is None else round(edge_ratios[0],4),
            "edge_ratio_may":None if edge_ratios[1] is None else round(edge_ratios[1],4),
            "edge_ratio_june":None if edge_ratios[2] is None else round(edge_ratios[2],4),
            "edge_ratio_july":None if edge_ratios[3] is None else round(edge_ratios[3],4),
        }
        field_rows.append(rec)
        if locked_pass:
            for k,cm in enumerate(comps):
                geom=b2.mask_geom(cm,transform,row.geometry)
                if geom is not None:
                    child_rows.append({"candidate_field_id_2026":f"{fid}::C{k+1}","parent_field_id_2025":fid,"change_type":"SPLIT","cluster":k+1,"geometry":geom})

    fdf=pd.DataFrame(field_rows)

    # Create C adjacency locally, then run the unchanged B2 merge-candidate logic.
    sidx=g.sindex; pairs=[]; seen=set()
    for idx,row in g.iterrows():
        for p in sidx.query(row.geometry.buffer(3.0),predicate="intersects"):
            j=int(p)
            if j==idx: continue
            a=str(row["parent_field_id_2025"]); b=str(g.loc[j,"parent_field_id_2025"])
            key=tuple(sorted((a,b)))
            if key in seen: continue
            d=float(row.geometry.distance(g.loc[j].geometry))
            if d>3.0: continue
            seen.add(key)
            shared=float(row.geometry.boundary.intersection(g.loc[j].geometry.boundary).length)
            pairs.append({"field_a":key[0],"field_b":key[1],"distance_m":d,"shared_boundary_m":shared})
    adj=pd.DataFrame(pairs)

    # Ensure stats for non-split/uncertain fields when possible.
    for pos,row in g.iterrows():
        fid=str(row["parent_field_id_2025"])
        if fid in field_stats: continue
        m=(labels==(pos+1))&all_valid
        if m.sum()>=4:
            x=z[m]; mu=x.mean(axis=0); field_stats[fid]={"mean":mu,"within":b2.rms(x-mu),"mask":labels==(pos+1)}

    mg=b2cfg["merge"]; merge_rows=[]; merge_geoms=[]
    for pair in adj.itertuples(index=False):
        a=str(pair.field_a); b=str(pair.field_b)
        if a not in id_to_pos or b not in id_to_pos or a not in field_stats or b not in field_stats: continue
        ia=id_to_pos[a]; ib=id_to_pos[b]
        ma=labels==(ia+1); mb=labels==(ib+1)
        strip_a=ma & ndi.binary_dilation(mb,iterations=int(mg["boundary_dilation_pixels"]),structure=np.ones((3,3),dtype=bool))
        strip_b=mb & ndi.binary_dilation(ma,iterations=int(mg["boundary_dilation_pixels"]),structure=np.ones((3,3),dtype=bool))
        boundary=[]; valid_snaps=0; strong=0
        for sidx2 in range(4):
            va=strip_a&valids[sidx2]; vb=strip_b&valids[sidx2]
            if va.sum()<int(mg["minimum_strip_pixels_per_side"]) or vb.sum()<int(mg["minimum_strip_pixels_per_side"]):
                boundary.append(None); continue
            sl=slice(sidx2*dims_per,(sidx2+1)*dims_per)
            da=b2.rms(z[va][:,sl].mean(axis=0)-z[vb][:,sl].mean(axis=0))
            boundary.append(da); valid_snaps+=1; strong+=int(da>=float(mg["strong_edge_distance"]))
        fs_a=field_stats[a]; fs_b=field_stats[b]
        field_dist=b2.rms(fs_a["mean"]-fs_b["mean"])
        pooled=0.5*(float(fs_a["within"])+float(fs_b["within"]))
        bw_ratio=field_dist/max(pooled,0.15)
        vals=[v for v in boundary if v is not None]
        bmed=float(np.median(vals)) if vals else None
        sim_field=math.exp(-field_dist); sim_boundary=math.exp(-bmed) if bmed is not None else 0.0
        stability=(valid_snaps/4.0)*(1.0-strong/4.0)
        conf=0.45*sim_field+0.40*sim_boundary+0.15*stability
        cand=(valid_snaps>=int(mg["minimum_valid_boundary_snapshots"]) and field_dist<=float(mg["maximum_field_mean_distance"]) and
              bw_ratio<=float(mg["maximum_between_within_ratio"]) and bmed is not None and bmed<=float(mg["maximum_boundary_median_distance"]) and
              strong<=int(mg["maximum_strong_edge_snapshots"]) and conf>=float(mg["minimum_confidence"]))
        merge_rows.append({"field_a":a,"field_b":b,"change_type":"MERGE_CANDIDATE" if cand else "KEEP_BOUNDARY","confidence":round(conf,4),
                           "field_mean_distance":round(field_dist,4),"between_within_ratio":round(bw_ratio,4),"boundary_median_distance":None if bmed is None else round(bmed,4),
                           "valid_boundary_snapshots":valid_snaps,"strong_edge_snapshots":strong,
                           "edge_april":None if boundary[0] is None else round(boundary[0],4),"edge_may":None if boundary[1] is None else round(boundary[1],4),
                           "edge_june":None if boundary[2] is None else round(boundary[2],4),"edge_july":None if boundary[3] is None else round(boundary[3],4)})
        if cand:
            ca=g.loc[ia].geometry.centroid; cb=g.loc[ib].geometry.centroid
            merge_geoms.append({"field_a":a,"field_b":b,"change_type":"MERGE_CANDIDATE","confidence":round(conf,4),"geometry":LineString([ca,cb])})

    mdf=pd.DataFrame(merge_rows)
    fdf.to_csv(out/"c2_field_validation.csv",index=False)
    adj.to_csv(out/"c2_adjacency.csv",index=False)
    mdf.to_csv(out/"c2_boundary_validation.csv",index=False)
    if child_rows:
        gpd.GeoDataFrame(child_rows,geometry="geometry",crs=32633).to_file(out/"c2_locked_split_children.gpkg",layer="split_children",driver="GPKG")
    if merge_geoms:
        gpd.GeoDataFrame(merge_geoms,geometry="geometry",crs=32633).to_file(out/"c2_merge_candidates.gpkg",layer="merge_candidates",driver="GPKG")

    baseline=int((fdf["discovery_type"]=="SPLIT_CANDIDATE").sum())
    locked_n=int(fdf.get("locked_split_pass",pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    uncertain=int((fdf["discovery_type"]=="UNCERTAIN").sum())
    merge_n=int((mdf["change_type"]=="MERGE_CANDIDATE").sum()) if len(mdf) else 0
    summary={
      "schema_version":"akerpuls-prelim-fields-2026-c2-locked-validation-v1","status":"PASS",
      "pilot_fields":len(g),"all_valid_pixel_fraction":round(float(all_valid[labels>0].mean()),6),
      "baseline_split_candidates":baseline,"baseline_split_rate":round(baseline/len(g),4),
      "locked_split_candidates":locked_n,"locked_split_rate":round(locked_n/len(g),4),
      "locked_retention_of_baseline":round(locked_n/max(1,baseline),4),"uncertain_fields":uncertain,
      "adjacency_pairs":len(adj),"merge_candidates":merge_n,"merge_candidate_rate":round(merge_n/max(1,len(adj)),4),
      "candidate_discovery_contract":"IDENTICAL_TO_B2","locked_split_rule":cfg["locked_split_rule"],"merge_policy":cfg["merge_policy"],
      "sentinel_hub_pu_used":0,"thresholds_tuned":False,"thresholds_frozen":False,
      "next_step":"C3 blind visual QA of locked split positives plus high-score locked rejects; no tuning until review is complete."
    }
    (out/"c2_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C2 LOCKED INDEPENDENT VALIDATION")
    print(f'PILOT_FIELDS={len(g)} ALL_VALID_PIXEL_FRACTION={summary["all_valid_pixel_fraction"]:.4f}')
    print(f'BASELINE_SPLITS={baseline}/{len(g)} RATE={summary["baseline_split_rate"]:.4f}')
    print(f'LOCKED_SPLITS={locked_n}/{len(g)} RATE={summary["locked_split_rate"]:.4f} RETENTION={summary["locked_retention_of_baseline"]:.4f}')
    print(f'UNCERTAIN_FIELDS={uncertain}/{len(g)}')
    print(f'ADJACENCY_PAIRS={len(adj)} MERGE_CANDIDATES={merge_n} RATE={summary["merge_candidate_rate"]:.4f} POLICY={cfg["merge_policy"]}')
    print("CANDIDATE_DISCOVERY_CONTRACT=IDENTICAL_TO_B2")
    print("THRESHOLDS_TUNED=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C2_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
