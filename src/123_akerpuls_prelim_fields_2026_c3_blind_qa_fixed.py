#!/usr/bin/env python3
"""STOPPUNKT C3: validity strata + blinded visual QA, corrected before first run. Zero PU."""
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

def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def spaced(df,n,col):
    x=df.sort_values(col,ascending=False).reset_index(drop=True)
    if len(x)<=n: return x.copy()
    pos=sorted(set(round(i*(len(x)-1)/(n-1)) for i in range(n)))
    return x.iloc[pos].copy()

def hsh(salt,fid): return hashlib.sha256(f"{salt}|{fid}".encode()).hexdigest()

def render(index,fid,parent,children,rdir,path,b3):
    import rasterio
    from PIL import Image,ImageDraw
    panels=[]; bounds=parent.buffer(80).bounds
    for snap in SNAPS:
        with rasterio.open(rdir/f"{snap.lower()}.tif") as ds:
            win=b3.bounds_to_window(bounds,ds.transform,ds.width,ds.height,pad_px=3)
            ix={n:i+1 for i,n in enumerate(ds.descriptions) if n}
            rgb=np.stack([ds.read(ix["B04"],window=win),ds.read(ix["B03"],window=win),ds.read(ix["B02"],window=win)])
            valid=ds.read(ix["VALID"],window=win)>0.5
            im=b3.stretch_rgb(rgb)
            if (~valid).any():
                im[~valid]=(0.35*im[~valid].astype(float)+0.65*np.array([255,40,80])).astype(np.uint8)
            im=b3.overlay_geom(im,[parent],win,ds.transform,[255,255,255])
            im=b3.overlay_geom(im,children,win,ds.transform,[0,0,0])
            p=Image.fromarray(im).resize((280,280)); c=Image.new("RGB",(280,305),"white"); c.paste(p,(0,25))
            ImageDraw.Draw(c).text((5,5),snap,fill="black"); panels.append(c)
    sheet=Image.new("RGB",(1120,340),"white")
    for i,p in enumerate(panels): sheet.paste(p,(280*i,35))
    ImageDraw.Draw(sheet).text((5,8),f"C3 BLIND #{index:02d}  {fid}",fill="black")
    sheet.save(path)

def main():
    import geopandas as gpd, pandas as pd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize
    ap=argparse.ArgumentParser()
    ap.add_argument("--pilot-dir"); ap.add_argument("--raster-dir"); ap.add_argument("--c2-dir"); ap.add_argument("--output-dir")
    args=ap.parse_args()
    cfg=json.loads(CFG.read_text(encoding="utf-8")); c2cfg=json.loads(C2CFG.read_text(encoding="utf-8")); b2cfg=json.loads(B2CFG.read_text(encoding="utf-8"))
    if cfg["locked_split_rule"]!=c2cfg["locked_split_rule"]: raise RuntimeError("C3/C2 locked-rule mismatch")
    if any(bool(v) for v in cfg["guards"].values()): raise RuntimeError("Forbidden C3 scope enabled")
    pdir=Path(args.pilot_dir or cfg["pilot_dir"]); rdir=Path(args.raster_dir or cfg["raster_dir"]); cdir=Path(args.c2_dir or cfg["c2_dir"]); out=Path(args.output_dir or cfg["output_dir"])
    imgdir=out/"blind_images"; imgdir.mkdir(parents=True,exist_ok=True)
    c2sum=json.loads((cdir/"c2_summary.json").read_text(encoding="utf-8"))
    if c2sum.get("status")!="PASS" or c2sum.get("thresholds_tuned") is not False: raise RuntimeError("C2 is not an untuned PASS")
    f=pd.read_csv(cdir/"c2_field_validation.csv",dtype={"parent_field_id_2025":str}); v=pd.read_csv(rdir/"field_snapshot_validity.csv",dtype={"parent_field_id_2025":str})
    g=gpd.read_file(pdir/"c0_pilot_fields_2025.gpkg").to_crs(32633).reset_index(drop=True)
    if len(f)!=1000 or len(g)!=1000: raise RuntimeError("C3 expected 1000 C fields")
    x=f.merge(v,on="parent_field_id_2025",how="left",validate="one_to_one")
    jc="valid_s2_2026_july"; hi=float(cfg["validity_strata"]["high_july_min"]); mid=float(cfg["validity_strata"]["medium_july_min"])
    x["july_validity_stratum"]=np.where(x[jc]>=hi,"HIGH_GE80",np.where(x[jc]>=mid,"MED_50_80","LOW_LT50"))
    x["is_uncertain"]=x.discovery_type.eq("UNCERTAIN"); x["is_baseline_split"]=x.discovery_type.eq("SPLIT_CANDIDATE"); x["is_locked_split"]=x.locked_split_pass.fillna(False).astype(bool)
    x["analysis_fraction"]=pd.to_numeric(x.analysis_pixels,errors="coerce")/pd.to_numeric(x.pixels,errors="coerce").replace(0,np.nan)
    x.to_csv(out/"c3_field_validity_join.csv",index=False)
    strata=[]
    for name in ["HIGH_GE80","MED_50_80","LOW_LT50"]:
        s=x[x.july_validity_stratum==name]
        strata.append({"july_validity_stratum":name,"fields":len(s),"uncertain":int(s.is_uncertain.sum()),"uncertain_rate":round(float(s.is_uncertain.mean()) if len(s) else 0,4),"baseline_splits":int(s.is_baseline_split.sum()),"baseline_split_rate":round(float(s.is_baseline_split.mean()) if len(s) else 0,4),"locked_splits":int(s.is_locked_split.sum()),"locked_split_rate":round(float(s.is_locked_split.mean()) if len(s) else 0,4),"median_analysis_fraction":None if not len(s) else round(float(s.analysis_fraction.median()),4)})
    pd.DataFrame(strata).to_csv(out/"c3_validity_strata.csv",index=False)

    n=int(cfg["blind_visual_set"]["locked_pass_representative"]); passpick=spaced(x[x.is_locked_split].copy(),n,"separation_ratio")
    r=x[x.is_baseline_split & ~x.is_locked_split].copy(); rule=cfg["locked_split_rule"]
    r["fail_lcf"]=(pd.to_numeric(r.min_largest_component_fraction,errors="coerce")<float(rule["minimum_largest_component_fraction_each_child"])).astype(int)
    r["fail_edge"]=(pd.to_numeric(r.edge_support_count,errors="coerce")<int(rule["minimum_supporting_edge_snapshots"])).astype(int)
    r["fail_loo"]=(~r.loo_all4.fillna(False).astype(bool)).astype(int); r["failed_gates"]=r[["fail_lcf","fail_edge","fail_loo"]].sum(axis=1)
    r["lcf_gap"]=(float(rule["minimum_largest_component_fraction_each_child"])-pd.to_numeric(r.min_largest_component_fraction,errors="coerce")).clip(lower=0)
    r["edge_gap"]=(int(rule["minimum_supporting_edge_snapshots"])-pd.to_numeric(r.edge_support_count,errors="coerce")).clip(lower=0)
    r["challenge_score"]=r.failed_gates*100+r.lcf_gap*10+r.edge_gap
    rejectpick=r.sort_values(["failed_gates","challenge_score","separation_ratio"],ascending=[True,True,False]).head(int(cfg["blind_visual_set"]["locked_reject_challenge"])).copy()
    selected=pd.concat([passpick.assign(blind_source="LOCKED_PASS_REPRESENTATIVE"),rejectpick.assign(blind_source="LOCKED_REJECT_CHALLENGE")],ignore_index=True)
    salt=cfg["blind_visual_set"]["shuffle_salt"]; selected["blind_hash"]=[hsh(salt,str(z)) for z in selected.parent_field_id_2025]
    selected=selected.sort_values("blind_hash").reset_index(drop=True); selected["blind_index"]=np.arange(1,len(selected)+1)

    b2=load_module(B2SCRIPT,"c3_b2"); b3=load_module(B3SCRIPT,"c3_b3"); feats=list(b2cfg["feature_bands_per_snapshot"])
    cubes,valids,_rgb,transform,crs,(h,w)=b2.load_snapshots(rdir,feats)
    labels=rasterize([(geom,i+1) for i,geom in enumerate(g.geometry)],out_shape=(h,w),transform=transform,fill=0,dtype="int32",all_touched=False); allvalid=np.logical_and.reduce(valids)
    raw=np.concatenate(cubes,axis=0).transpose(1,2,0); sample=raw[(labels>0)&allvalid]; center=np.nanmedian(sample,axis=0); mad=np.nanmedian(np.abs(sample-center),axis=0)*1.4826; std=np.nanstd(sample,axis=0); scale=np.where(mad>1e-6,mad,np.where(std>1e-6,std,1.0)); z=(raw-center)/scale
    idpos={str(fid):i for i,fid in enumerate(g.parent_field_id_2025.astype(str))}; sp=b2cfg["split"]; key=[]
    for _,rec in selected.iterrows():
        fid=str(rec.parent_field_id_2025); pos=idpos[fid]; parent=g.loc[pos].geometry; fm=labels==(pos+1)
        interior=ndi.binary_erosion(fm,structure=np.ones((3,3),dtype=bool),iterations=int(sp["interior_erosion_pixels"]),border_value=0)
        if interior.sum()<int(sp["minimum_valid_pixels"]): interior=fm.copy()
        m=interior&allvalid; fit=b2.deterministic_k2(z[m])
        if fit is None: raise RuntimeError(f"Cannot reconstruct candidate {fid}")
        lab=fit[0]; ci=np.full((h,w),-1,dtype=np.int8); ci[m]=lab; children=[]
        for k in [0,1]:
            cm,_=b2.largest_component(ci==k,ndi); geom=b2.mask_geom(cm,transform,parent)
            if geom is not None: children.append(geom)
        if len(children)!=2: raise RuntimeError(f"Expected two children for {fid}")
        bi=int(rec.blind_index); render(bi,fid,parent,children,rdir,imgdir/f"C3_{bi:02d}.png",b3)
        key.append({"blind_index":bi,"parent_field_id_2025":fid,"hidden_group":str(rec.blind_source),"locked_split_pass":bool(rec.locked_split_pass),"july_validity":float(rec[jc]),"july_validity_stratum":str(rec.july_validity_stratum),"separation_ratio":float(rec.separation_ratio),"min_largest_component_fraction":float(rec.min_largest_component_fraction),"edge_support_count":int(rec.edge_support_count),"loo_all4":bool(rec.loo_all4)})
    kd=pd.DataFrame(key).sort_values("blind_index"); kp=out/"c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"; kd.to_csv(kp,index=False); kh=hashlib.sha256(kp.read_bytes()).hexdigest()
    summary={"schema_version":"akerpuls-prelim-fields-2026-c3-blind-qa-v1","status":"PASS","pilot_fields":len(x),"baseline_splits":int(x.is_baseline_split.sum()),"locked_splits":int(x.is_locked_split.sum()),"uncertain_fields":int(x.is_uncertain.sum()),"validity_strata":strata,"blind_images":len(kd),"blind_pass_source_images":int((kd.hidden_group=="LOCKED_PASS_REPRESENTATIVE").sum()),"blind_reject_source_images":int((kd.hidden_group=="LOCKED_REJECT_CHALLENGE").sum()),"blind_key_sha256":kh,"locked_split_rule":cfg["locked_split_rule"],"merge_policy":cfg["merge_policy"],"sentinel_hub_pu_used":0,"thresholds_tuned":False,"thresholds_frozen":False,"warning":"Blind set is a diagnostic challenge set, not a random accuracy sample.","next_step":"Review C3_01..C3_20 without opening key; reveal key only after labels are fixed."}
    (out/"c3_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C3 VALIDITY STRATA + BLIND QA")
    for s in strata: print(f'JULY_{s["july_validity_stratum"]}: FIELDS={s["fields"]} UNCERTAIN={s["uncertain"]} RATE={s["uncertain_rate"]:.4f} BASELINE_SPLITS={s["baseline_splits"]} LOCKED_SPLITS={s["locked_splits"]} ANALYSIS_MED={s["median_analysis_fraction"]}')
    print(f'BLIND_IMAGES={len(kd)} HIDDEN_PASS_SOURCE={summary["blind_pass_source_images"]} HIDDEN_REJECT_SOURCE={summary["blind_reject_source_images"]}')
    print(f"BLIND_KEY_SHA256={kh}"); print("DO_NOT_OPEN_BLIND_KEY_BEFORE_VISUAL_REVIEW=TRUE"); print("THRESHOLDS_TUNED=FALSE"); print("SENTINEL_HUB_PU_USED=0"); print("C3_STATUS=PASS"); print("OUTPUT="+str(out)); return 0

if __name__=="__main__": raise SystemExit(main())
