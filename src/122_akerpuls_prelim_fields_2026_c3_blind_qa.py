#!/usr/bin/env python3
"""STOPPUNKT C3: validity-stratified diagnostics + blinded visual QA. Zero API calls."""
from __future__ import annotations

import argparse, hashlib, importlib.util, json, math
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_c3.json"
C2CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_c2.json"
B2CFG=ROOT/"config"/"akerpuls_prelim_fields_2026_b2.json"
B2SCRIPT=ROOT/"src"/"113_akerpuls_prelim_fields_2026_b2_baseline.py"
B3SCRIPT=ROOT/"src"/"114_akerpuls_prelim_fields_2026_b3_qa.py"
SNAPS=["S2_2026_APRIL","S2_2026_MAY","S2_2026_JUNE","S2_2026_JULY"]


def load_module(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def evenly_spaced(frame, wanted, sort_col, ascending=False):
    if len(frame)<=wanted:
        return frame.sort_values(sort_col,ascending=ascending).copy()
    x=frame.sort_values(sort_col,ascending=ascending).reset_index(drop=True)
    pos=sorted(set(round(i*(len(x)-1)/(wanted-1)) for i in range(wanted))) if wanted>1 else [len(x)//2]
    return x.iloc[pos].copy()


def blind_hash(salt, fid):
    return hashlib.sha256(f"{salt}|{fid}".encode("utf-8")).hexdigest()


def render_blind(index, fid, parent_geom, child_geoms, raster_dir, out_file, b3):
    import rasterio
    from PIL import Image, ImageDraw

    bounds=parent_geom.buffer(80).bounds
    panels=[]
    for snap in SNAPS:
        path=raster_dir/f"{snap.lower()}.tif"
        with rasterio.open(path) as ds:
            win=b3.bounds_to_window(bounds,ds.transform,ds.width,ds.height,pad_px=3)
            idx={n:i+1 for i,n in enumerate(ds.descriptions) if n}
            rgb=np.stack([
                ds.read(idx["B04"],window=win),
                ds.read(idx["B03"],window=win),
                ds.read(idx["B02"],window=win),
            ])
            valid=ds.read(idx["VALID"],window=win)>0.5
            img=b3.stretch_rgb(rgb)
            if (~valid).any():
                tint=np.array([255,40,80],dtype=np.float32)
                p=img[~valid].astype(np.float32)
                img[~valid]=(0.35*p+0.65*tint).astype(np.uint8)
            img=b3.overlay_geom(img,[parent_geom],win,ds.transform,[255,255,255])
            img=b3.overlay_geom(img,child_geoms,win,ds.transform,[0,0,0])
            im=Image.fromarray(img).resize((280,280))
            canvas=Image.new("RGB",(280,305),"white")
            canvas.paste(im,(0,25))
            d=ImageDraw.Draw(canvas)
            d.text((5,5),snap,fill="black")
            panels.append(canvas)
    sheet=Image.new("RGB",(1120,340),"white")
    for i,p in enumerate(panels):
        sheet.paste(p,(i*280,35))
    d=ImageDraw.Draw(sheet)
    d.text((5,8),f"C3 BLIND #{index:02d}  {fid}",fill="black")
    sheet.save(out_file)


def main():
    import geopandas as gpd
    import pandas as pd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize

    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir")
    ap.add_argument("--raster-dir")
    ap.add_argument("--c2-dir")
    ap.add_argument("--output-dir")
    args=ap.parse_args()

    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    c2cfg=json.loads(C2CFG.read_text(encoding="utf-8"))
    b2cfg=json.loads(B2CFG.read_text(encoding="utf-8"))
    if cfg["locked_split_rule"]!=c2cfg["locked_split_rule"]:
        raise RuntimeError("C3 locked split rule differs from C2")
    if any(bool(v) for v in cfg["guards"].values()):
        raise RuntimeError("C3 guards unexpectedly enable forbidden scope")

    pdir=Path(args.pilot_dir or cfg["pilot_dir"])
    rdir=Path(args.raster_dir or cfg["raster_dir"])
    cdir=Path(args.c2_dir or cfg["c2_dir"])
    out=Path(args.output_dir or cfg["output_dir"])
    imgdir=out/"blind_images"
    imgdir.mkdir(parents=True,exist_ok=True)

    c2sum=json.loads((cdir/"c2_summary.json").read_text(encoding="utf-8"))
    if c2sum.get("status")!="PASS" or bool(c2sum.get("thresholds_tuned")):
        raise RuntimeError("C2 is not an untuned PASS")

    fdf=pd.read_csv(cdir/"c2_field_validation.csv",dtype={"parent_field_id_2025":str})
    vdf=pd.read_csv(rdir/"field_snapshot_validity.csv",dtype={"parent_field_id_2025":str})
    g=gpd.read_file(pdir/"c0_pilot_fields_2025.gpkg").to_crs(32633).reset_index(drop=True)
    if len(g)!=1000 or len(fdf)!=1000:
        raise RuntimeError(f"Expected 1000 C fields; geometry={len(g)} validation={len(fdf)}")

    july_col="valid_s2_2026_july"
    if july_col not in vdf.columns:
        raise RuntimeError(f"C1 validity missing {july_col}")
    x=fdf.merge(vdf,on="parent_field_id_2025",how="left",validate="one_to_one")
    high=float(cfg["validity_strata"]["high_july_min"])
    medium=float(cfg["validity_strata"]["medium_july_min"])
    x["july_validity_stratum"]=np.where(x[july_col]>=high,"HIGH_GE80",np.where(x[july_col]>=medium,"MED_50_80","LOW_LT50"))
    x["is_uncertain"]=x["discovery_type"].eq("UNCERTAIN")
    x["is_baseline_split"]=x["discovery_type"].eq("SPLIT_CANDIDATE")
    x["is_locked_split"]=x["locked_split_pass"].fillna(False).astype(bool)
    x["analysis_fraction"]=pd.to_numeric(x.get("analysis_pixels"),errors="coerce")/pd.to_numeric(x.get("pixels"),errors="coerce").replace(0,np.nan)
    x.to_csv(out/"c3_field_validity_join.csv",index=False)

    strata=[]
    for name in ("HIGH_GE80","MED_50_80","LOW_LT50"):
        s=x[x["july_validity_stratum"]==name]
        strata.append({
            "july_validity_stratum":name,
            "fields":int(len(s)),
            "uncertain":int(s["is_uncertain"].sum()),
            "uncertain_rate":round(float(s["is_uncertain"].mean()) if len(s) else 0.0,4),
            "baseline_splits":int(s["is_baseline_split"].sum()),
            "baseline_split_rate":round(float(s["is_baseline_split"].mean()) if len(s) else 0.0,4),
            "locked_splits":int(s["is_locked_split"].sum()),
            "locked_split_rate":round(float(s["is_locked_split"].mean()) if len(s) else 0.0,4),
            "median_analysis_fraction":None if not len(s) else round(float(s["analysis_fraction"].median(skipna=True)),4),
        })
    pd.DataFrame(strata).to_csv(out/"c3_validity_strata.csv",index=False)

    # Blind set: 10 representative locked positives + 10 difficult locked rejects.
    pass_pool=x[x["is_locked_split"]].copy()
    pass_pick=evenly_spaced(pass_pool,int(cfg["blind_visual_set"]["locked_pass_representative"]),"separation_ratio",ascending=False)

    reject_pool=x[x["is_baseline_split"] & ~x["is_locked_split"]].copy()
    locked=cfg["locked_split_rule"]
    reject_pool["fail_lcf"]=(pd.to_numeric(reject_pool["min_largest_component_fraction"],errors="coerce")<float(locked["minimum_largest_component_fraction_each_child"])).astype(int)
    reject_pool["fail_edge"]=(pd.to_numeric(reject_pool["edge_support_count"],errors="coerce")<int(locked["minimum_supporting_edge_snapshots"])).astype(int)
    reject_pool["fail_loo"]=(~reject_pool["loo_all4"].fillna(False).astype(bool)).astype(int)
    reject_pool["failed_gates"]=reject_pool[["fail_lcf","fail_edge","fail_loo"]].sum(axis=1)
    reject_pool["lcf_gap"]=(float(locked["minimum_largest_component_fraction_each_child"])-pd.to_numeric(reject_pool["min_largest_component_fraction"],errors="coerce")).clip(lower=0)
    reject_pool["edge_gap"]=(int(locked["minimum_supporting_edge_snapshots"])-pd.to_numeric(reject_pool["edge_support_count"],errors="coerce")).clip(lower=0)
    reject_pool["challenge_score"]=reject_pool["failed_gates"]*100 + reject_pool["lcf_gap"]*10 + reject_pool["edge_gap"]
    reject_pick=reject_pool.sort_values(["failed_gates","challenge_score","separation_ratio"],ascending=[True,True,False]).head(int(cfg["blind_visual_set"]["locked_reject_challenge"])).copy()

    selected=pd.concat([
        pass_pick.assign(_blind_source="LOCKED_PASS_REPRESENTATIVE"),
        reject_pick.assign(_blind_source="LOCKED_REJECT_CHALLENGE")
    ],ignore_index=True)
    salt=cfg["blind_visual_set"]["shuffle_salt"]
    selected["_blind_hash"]=[blind_hash(salt,str(fid)) for fid in selected["parent_field_id_2025"]]
    selected=selected.sort_values("_blind_hash").reset_index(drop=True)
    selected["blind_index"]=np.arange(1,len(selected)+1)

    # Reconstruct B2 split children using the identical C2 global scaling, only for rendering.
    b2=load_module(B2SCRIPT,"akerpuls_b2_for_c3")
    b3=load_module(B3SCRIPT,"akerpuls_b3_for_c3")
    features=list(b2cfg["feature_bands_per_snapshot"])
    cubes,valids,_rgbs,transform,crs,(h,w)=b2.load_snapshots(rdir,features)
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
    sp=b2cfg["split"]
    id_to_pos={str(fid):i for i,fid in enumerate(g["parent_field_id_2025"].astype(str))}

    key_rows=[]
    for rec in selected.itertuples(index=False):
        fid=str(rec.parent_field_id_2025)
        pos=id_to_pos[fid]
        row=g.loc[pos]
        fm=labels==(pos+1)
        interior=ndi.binary_erosion(fm,structure=np.ones((3,3),dtype=bool),iterations=int(sp["interior_erosion_pixels"]),border_value=0)
        if interior.sum()<int(sp["minimum_valid_pixels"]):
            interior=fm.copy()
        m=interior&all_valid
        fit=b2.deterministic_k2(z[m])
        if fit is None:
            raise RuntimeError(f"C3 could not reconstruct B2 k2 for selected candidate {fid}")
        lab,_c,_between,_win=fit
        cluster_img=np.full((h,w),-1,dtype=np.int8); cluster_img[m]=lab
        child_geoms=[]
        for k in (0,1):
            cm,_count=b2.largest_component(cluster_img==k,ndi)
            geom=b2.mask_geom(cm,transform,row.geometry)
            if geom is not None:
                child_geoms.append(geom)
        if len(child_geoms)!=2:
            raise RuntimeError(f"C3 expected two rendered children for {fid}, got {len(child_geoms)}")
        outfile=imgdir/f"{cfg['blind_visual_set']['filename_prefix']}_{int(rec.blind_index):02d}.png"
        render_blind(int(rec.blind_index),fid,row.geometry,child_geoms,rdir,outfile,b3)
        key_rows.append({
            "blind_index":int(rec.blind_index),
            "parent_field_id_2025":fid,
            "hidden_group":rec._blind_source,
            "locked_split_pass":bool(rec.locked_split_pass),
            "july_validity":float(getattr(rec,july_col)),
            "july_validity_stratum":rec.july_validity_stratum,
            "separation_ratio":None if pd.isna(rec.separation_ratio) else float(rec.separation_ratio),
            "min_largest_component_fraction":None if pd.isna(rec.min_largest_component_fraction) else float(rec.min_largest_component_fraction),
            "edge_support_count":None if pd.isna(rec.edge_support_count) else int(rec.edge_support_count),
            "loo_all4":bool(rec.loo_all4) if not pd.isna(rec.loo_all4) else False,
        })

    key=pd.DataFrame(key_rows).sort_values("blind_index")
    key.to_csv(out/"c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv",index=False)
    key_hash=hashlib.sha256((out/"c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv").read_bytes()).hexdigest()

    summary={
      "schema_version":"akerpuls-prelim-fields-2026-c3-blind-qa-v1",
      "status":"PASS",
      "pilot_fields":int(len(x)),
      "baseline_splits":int(x["is_baseline_split"].sum()),
      "locked_splits":int(x["is_locked_split"].sum()),
      "uncertain_fields":int(x["is_uncertain"].sum()),
      "validity_strata":strata,
      "blind_images":int(len(key)),
      "blind_pass_source_images":int((key["hidden_group"]=="LOCKED_PASS_REPRESENTATIVE").sum()),
      "blind_reject_source_images":int((key["hidden_group"]=="LOCKED_REJECT_CHALLENGE").sum()),
      "blind_key_sha256":key_hash,
      "locked_split_rule":cfg["locked_split_rule"],
      "merge_policy":cfg["merge_policy"],
      "sentinel_hub_pu_used":0,
      "thresholds_tuned":False,
      "thresholds_frozen":False,
      "warning":"Blind image set is a diagnostic challenge set, not a random accuracy sample. Do not use its raw fraction as precision or recall.",
      "next_step":"Review C3_01..C3_20 without opening the key. Reveal key only after visual labels are fixed."
    }
    (out/"c3_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C3 VALIDITY STRATA + BLIND QA")
    for s in strata:
        print(f'JULY_{s["july_validity_stratum"]}: FIELDS={s["fields"]} UNCERTAIN={s["uncertain"]} RATE={s["uncertain_rate"]:.4f} BASELINE_SPLITS={s["baseline_splits"]} LOCKED_SPLITS={s["locked_splits"]} ANALYSIS_MED={s["median_analysis_fraction"]}')
    print(f'BLIND_IMAGES={len(key)} HIDDEN_PASS_SOURCE={summary["blind_pass_source_images"]} HIDDEN_REJECT_SOURCE={summary["blind_reject_source_images"]}')
    print(f'BLIND_KEY_SHA256={key_hash}')
    print("DO_NOT_OPEN_BLIND_KEY_BEFORE_VISUAL_REVIEW=TRUE")
    print("THRESHOLDS_TUNED=FALSE")
    print("SENTINEL_HUB_PU_USED=0")
    print("C3_STATUS=PASS")
    print("OUTPUT="+str(out))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
