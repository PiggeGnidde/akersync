#!/usr/bin/env python3
"""STOPPUNKT C5c: third-holdout validation of frozen split rules. Zero API calls."""
from __future__ import annotations
import argparse, importlib.util, json, math
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/'config'/'akerpuls_prelim_fields_2026_c5c.json'
C5ACFG=ROOT/'config'/'akerpuls_prelim_fields_2026_c5a.json'
C5BCFG=ROOT/'config'/'akerpuls_prelim_fields_2026_c5b.json'
B2CFG=ROOT/'config'/'akerpuls_prelim_fields_2026_b2.json'
B2SCRIPT=ROOT/'src'/'113_akerpuls_prelim_fields_2026_b2_baseline.py'
B4SCRIPT=ROOT/'src'/'115_akerpuls_prelim_fields_2026_b4_diagnostic.py'
B3SCRIPT=ROOT/'src'/'114_akerpuls_prelim_fields_2026_b3_qa.py'


def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def main():
    import geopandas as gpd, pandas as pd
    from scipy import ndimage as ndi
    from rasterio.features import rasterize
    from shapely.geometry import LineString

    ap=argparse.ArgumentParser()
    ap.add_argument('--pilot-dir'); ap.add_argument('--raster-dir'); ap.add_argument('--output-dir')
    args=ap.parse_args()
    cfg=json.loads(CFG.read_text(encoding='utf-8'))
    a=json.loads(C5ACFG.read_text(encoding='utf-8'))
    b=json.loads(C5BCFG.read_text(encoding='utf-8'))
    b2cfg=json.loads(B2CFG.read_text(encoding='utf-8'))

    if cfg['candidate_discovery_contract']!='IDENTICAL_TO_B2': raise RuntimeError('C5c discovery contract changed')
    if cfg['split_candidate_rule_frozen_for_test']!=a['split_candidate_rule_frozen_for_test'] or cfg['split_candidate_rule_frozen_for_test']!=b['split_candidate_rule_frozen_for_test']:
        raise RuntimeError('C5c split-candidate rule mismatch')
    if cfg['high_confidence_rule_frozen_for_test']!=a['high_confidence_rule_frozen_for_test'] or cfg['high_confidence_rule_frozen_for_test']!=b['high_confidence_rule_frozen_for_test']:
        raise RuntimeError('C5c high-confidence rule mismatch')
    if cfg['guards'].get('threshold_tuning') is not False: raise RuntimeError('Threshold tuning enabled')

    pdir=Path(args.pilot_dir or cfg['pilot_dir']); rdir=Path(args.raster_dir or cfg['raster_dir']); out=Path(args.output_dir or cfg['output_dir']); out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((rdir/'c5b_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status')!='PASS' or manifest.get('preprocessing_contract')!='IDENTICAL_TO_B1' or manifest.get('thresholds_tuned') is not False:
        raise RuntimeError('C5b is not a clean PASS')
    if manifest.get('split_candidate_rule_frozen_for_test')!=cfg['split_candidate_rule_frozen_for_test'] or manifest.get('high_confidence_rule_frozen_for_test')!=cfg['high_confidence_rule_frozen_for_test']:
        raise RuntimeError('C5b manifest rule mismatch')

    b2=load_module(B2SCRIPT,'c5c_b2'); b4=load_module(B4SCRIPT,'c5c_b4'); b3=load_module(B3SCRIPT,'c5c_b3')
    g=gpd.read_file(pdir/'c5a_pilot_fields_2025.gpkg').to_crs(32633).reset_index(drop=True)
    if len(g)!=int(cfg['expected_pilot_fields']): raise RuntimeError(f'Expected 1000 fields, got {len(g)}')
    features=list(b2cfg['feature_bands_per_snapshot'])
    cubes,valids,_rgbs,transform,crs,(h,w)=b2.load_snapshots(rdir,features)
    labels=rasterize([(geom,i+1) for i,geom in enumerate(g.geometry)],out_shape=(h,w),transform=transform,fill=0,dtype='int32',all_touched=False)
    all_valid=np.logical_and.reduce(valids)
    raw=np.concatenate(cubes,axis=0).transpose(1,2,0)
    sample=raw[(labels>0)&all_valid]
    if len(sample)==0: raise RuntimeError('No all-valid holdout pixels')
    center=np.nanmedian(sample,axis=0); mad=np.nanmedian(np.abs(sample-center),axis=0)*1.4826; std=np.nanstd(sample,axis=0)
    scale=np.where(mad>1e-6,mad,np.where(std>1e-6,std,1.0)); z=(raw-center)/scale; dims_per=len(features)
    ids=g['parent_field_id_2025'].astype(str).tolist(); id_to_pos={fid:i for i,fid in enumerate(ids)}
    sp=b2cfg['split']; locked=cfg['split_candidate_rule_frozen_for_test']; hc=cfg['high_confidence_rule_frozen_for_test']
    field_rows=[]; child_rows=[]; field_stats={}

    for pos,row in g.iterrows():
        fid=str(row['parent_field_id_2025']); fm=labels==(pos+1)
        interior=ndi.binary_erosion(fm,structure=np.ones((3,3),dtype=bool),iterations=int(sp['interior_erosion_pixels']),border_value=0)
        if interior.sum()<int(sp['minimum_valid_pixels']): interior=fm.copy()
        m=interior&all_valid; n=int(m.sum()); total=int(fm.sum())
        if n<int(sp['minimum_valid_pixels']):
            field_rows.append({'parent_field_id_2025':fid,'discovery_type':'UNCERTAIN','split_candidate_pass':False,'high_confidence_split':False,'reason':'TOO_FEW_ALL_VALID_INTERIOR_PIXELS','pixels':total,'analysis_pixels':n}); continue
        x=z[m]; mu=x.mean(axis=0); field_stats[fid]={'mean':mu,'within':b2.rms(x-mu),'mask':fm}
        fit=b2.deterministic_k2(x)
        if fit is None:
            field_rows.append({'parent_field_id_2025':fid,'discovery_type':'UNCHANGED','split_candidate_pass':False,'high_confidence_split':False,'reason':'NO_STABLE_K2','pixels':total,'analysis_pixels':n}); continue
        lab,c,between,win=fit; sep_ratio=between/max(win,0.15)
        cluster_img=np.full((h,w),-1,dtype=np.int8); cluster_img[m]=lab
        comps=[]; counts=[]
        for k in (0,1):
            cm,count=b2.largest_component(cluster_img==k,ndi); comps.append(cm); counts.append(count)
        coherence=sum(counts)/max(1,n); fractions=[cc/max(1,n) for cc in counts]; minfrac=min(fractions); minpix=min(counts)
        support=0; snap_ratios=[]
        for sidx in range(4):
            sl=slice(sidx*dims_per,(sidx+1)*dims_per); d=b2.rms(c[0,sl]-c[1,sl]); xx=x[:,sl]
            rr=np.sqrt(np.mean((xx-c[lab][:,sl])**2,axis=1)); ww=float(np.sqrt(np.mean(rr**2))); ratio=d/max(ww,0.15)
            snap_ratios.append(ratio); support+=int(ratio>=float(sp['snapshot_support_ratio']))
        baseline=(minpix>=int(sp['minimum_child_pixels']) and minfrac>=float(sp['minimum_child_fraction']) and coherence>=float(sp['minimum_spatial_coherence']) and sep_ratio>=float(sp['minimum_total_separation_ratio']) and support>=int(sp['minimum_supporting_snapshots']))
        if not baseline:
            field_rows.append({'parent_field_id_2025':fid,'discovery_type':'UNCHANGED','split_candidate_pass':False,'high_confidence_split':False,'reason':'B2_DISCOVERY_FAIL','pixels':total,'analysis_pixels':n,'separation_ratio':round(sep_ratio,4),'spatial_coherence':round(coherence,4),'min_child_fraction':round(minfrac,4),'supporting_snapshots':support,'sep_april':round(snap_ratios[0],4),'sep_may':round(snap_ratios[1],4),'sep_june':round(snap_ratios[2],4),'sep_july':round(snap_ratios[3],4)}); continue

        c0=cluster_img==0; c1=cluster_img==1
        morph,iface=b4.morphology_metrics(c0,c1,interior,fm,ndi,abs(transform.a))
        edge=b4.split_edge_metrics(c0,c1,iface,z,valids,dims_per,ndi,2); edge_ratios=[r[2] for r in edge]
        edge_count=sum(v is not None and v>=float(locked['edge_ratio_threshold']) for v in edge_ratios)
        loo_row={'sep_april':snap_ratios[0],'sep_may':snap_ratios[1],'sep_june':snap_ratios[2],'sep_july':snap_ratios[3]}
        loo_all4=all(b3.split_loo_pass(loo_row,{'snapshot_support_ratio':1.25,'minimum_supporting_remaining_snapshots':2,'minimum_remaining_median_ratio':1.25}))
        lcf=min(float(morph['child0_largest_component_fraction']),float(morph['child1_largest_component_fraction']))
        candidate=(lcf>=float(locked['minimum_largest_component_fraction_each_child']) and edge_count>=int(locked['minimum_supporting_edge_snapshots']) and ((not bool(locked['require_loo_all4'])) or loo_all4))
        high=bool(candidate and sep_ratio>=float(hc['minimum_separation_ratio']))
        rec={'parent_field_id_2025':fid,'discovery_type':'SPLIT_CANDIDATE','split_candidate_pass':bool(candidate),'high_confidence_split':high,'reason':'HIGH_CONFIDENCE_SPLIT' if high else ('SPLIT_CANDIDATE' if candidate else 'LOCKED_RULE_REJECT'),'pixels':total,'analysis_pixels':n,'separation_ratio':round(sep_ratio,4),'spatial_coherence':round(coherence,4),'min_child_fraction':round(minfrac,4),'supporting_snapshots':support,'sep_april':round(snap_ratios[0],4),'sep_may':round(snap_ratios[1],4),'sep_june':round(snap_ratios[2],4),'sep_july':round(snap_ratios[3],4),'min_largest_component_fraction':round(lcf,4),'edge_support_count':int(edge_count),'loo_all4':bool(loo_all4),'edge_ratio_april':None if edge_ratios[0] is None else round(edge_ratios[0],4),'edge_ratio_may':None if edge_ratios[1] is None else round(edge_ratios[1],4),'edge_ratio_june':None if edge_ratios[2] is None else round(edge_ratios[2],4),'edge_ratio_july':None if edge_ratios[3] is None else round(edge_ratios[3],4)}
        field_rows.append(rec)
        if candidate:
            for k,cm in enumerate(comps):
                geom=b2.mask_geom(cm,transform,row.geometry)
                if geom is not None: child_rows.append({'candidate_field_id_2026':f'{fid}::C{k+1}','parent_field_id_2025':fid,'change_type':'SPLIT','split_candidate_pass':True,'high_confidence_split':high,'cluster':k+1,'geometry':geom})

    fdf=pd.DataFrame(field_rows)
    # Keep merge behavior informational/candidate-only and unchanged from B2.
    sidx=g.sindex; pairs=[]; seen=set()
    for idx,row in g.iterrows():
        for p in sidx.query(row.geometry.buffer(3.0),predicate='intersects'):
            j=int(p)
            if j==idx: continue
            aa=str(row['parent_field_id_2025']); bb=str(g.loc[j,'parent_field_id_2025']); key=tuple(sorted((aa,bb)))
            if key in seen: continue
            d=float(row.geometry.distance(g.loc[j].geometry))
            if d>3.0: continue
            seen.add(key); shared=float(row.geometry.boundary.intersection(g.loc[j].geometry.boundary).length); pairs.append({'field_a':key[0],'field_b':key[1],'distance_m':d,'shared_boundary_m':shared})
    adj=pd.DataFrame(pairs)
    for pos,row in g.iterrows():
        fid=str(row['parent_field_id_2025'])
        if fid in field_stats: continue
        m=(labels==(pos+1))&all_valid
        if m.sum()>=4:
            x=z[m]; mu=x.mean(axis=0); field_stats[fid]={'mean':mu,'within':b2.rms(x-mu),'mask':labels==(pos+1)}
    mg=b2cfg['merge']; merge_rows=[]; merge_geoms=[]
    for pair in adj.itertuples(index=False):
        aa=str(pair.field_a); bb=str(pair.field_b)
        if aa not in id_to_pos or bb not in id_to_pos or aa not in field_stats or bb not in field_stats: continue
        ia=id_to_pos[aa]; ib=id_to_pos[bb]; ma=labels==(ia+1); mb=labels==(ib+1)
        sa=ma&ndi.binary_dilation(mb,iterations=int(mg['boundary_dilation_pixels']),structure=np.ones((3,3),dtype=bool)); sb=mb&ndi.binary_dilation(ma,iterations=int(mg['boundary_dilation_pixels']),structure=np.ones((3,3),dtype=bool))
        boundary=[]; valid_snaps=0; strong=0
        for si in range(4):
            va=sa&valids[si]; vb=sb&valids[si]
            if va.sum()<int(mg['minimum_strip_pixels_per_side']) or vb.sum()<int(mg['minimum_strip_pixels_per_side']): boundary.append(None); continue
            sl=slice(si*dims_per,(si+1)*dims_per); d=b2.rms(z[va][:,sl].mean(axis=0)-z[vb][:,sl].mean(axis=0)); boundary.append(d); valid_snaps+=1; strong+=int(d>=float(mg['strong_edge_distance']))
        fa=field_stats[aa]; fb=field_stats[bb]; fd=b2.rms(fa['mean']-fb['mean']); pooled=0.5*(float(fa['within'])+float(fb['within'])); bw=fd/max(pooled,0.15); vals=[v for v in boundary if v is not None]; bmed=float(np.median(vals)) if vals else None
        conf=0.45*math.exp(-fd)+0.40*(math.exp(-bmed) if bmed is not None else 0.0)+0.15*(valid_snaps/4.0)*(1.0-strong/4.0)
        cand=(valid_snaps>=int(mg['minimum_valid_boundary_snapshots']) and fd<=float(mg['maximum_field_mean_distance']) and bw<=float(mg['maximum_between_within_ratio']) and bmed is not None and bmed<=float(mg['maximum_boundary_median_distance']) and strong<=int(mg['maximum_strong_edge_snapshots']) and conf>=float(mg['minimum_confidence']))
        merge_rows.append({'field_a':aa,'field_b':bb,'change_type':'MERGE_CANDIDATE' if cand else 'KEEP_BOUNDARY','confidence':round(conf,4),'field_mean_distance':round(fd,4),'between_within_ratio':round(bw,4),'boundary_median_distance':None if bmed is None else round(bmed,4),'valid_boundary_snapshots':valid_snaps,'strong_edge_snapshots':strong})
        if cand:
            ca=g.loc[ia].geometry.centroid; cb=g.loc[ib].geometry.centroid; merge_geoms.append({'field_a':aa,'field_b':bb,'change_type':'MERGE_CANDIDATE','confidence':round(conf,4),'geometry':LineString([ca,cb])})
    mdf=pd.DataFrame(merge_rows)

    fdf.to_csv(out/'c5c_field_validation.csv',index=False); adj.to_csv(out/'c5c_adjacency.csv',index=False); mdf.to_csv(out/'c5c_boundary_validation.csv',index=False)
    if child_rows: gpd.GeoDataFrame(child_rows,geometry='geometry',crs=32633).to_file(out/'c5c_split_children.gpkg',layer='split_children',driver='GPKG')
    if merge_geoms: gpd.GeoDataFrame(merge_geoms,geometry='geometry',crs=32633).to_file(out/'c5c_merge_candidates.gpkg',layer='merge_candidates',driver='GPKG')

    baseline_n=int((fdf.discovery_type=='SPLIT_CANDIDATE').sum()); cand_n=int(fdf.split_candidate_pass.fillna(False).astype(bool).sum()); high_n=int(fdf.high_confidence_split.fillna(False).astype(bool).sum()); uncertain_n=int((fdf.discovery_type=='UNCERTAIN').sum()); merge_n=int((mdf.change_type=='MERGE_CANDIDATE').sum()) if len(mdf) else 0
    summary={'schema_version':'akerpuls-prelim-fields-2026-c5c-third-holdout-validation-v1','status':'PASS','pilot_fields':len(g),'all_valid_pixel_fraction':round(float(all_valid[labels>0].mean()),6),'baseline_split_candidates':baseline_n,'baseline_split_rate':round(baseline_n/len(g),4),'split_candidates':cand_n,'split_candidate_rate':round(cand_n/len(g),4),'candidate_retention_of_baseline':round(cand_n/max(1,baseline_n),4),'high_confidence_splits':high_n,'high_confidence_rate':round(high_n/len(g),4),'high_confidence_retention_of_candidates':round(high_n/max(1,cand_n),4),'uncertain_fields':uncertain_n,'adjacency_pairs':len(adj),'merge_candidates':merge_n,'merge_candidate_rate':round(merge_n/max(1,len(adj)),4),'candidate_discovery_contract':'IDENTICAL_TO_B2','split_candidate_rule_frozen_for_test':locked,'high_confidence_rule_frozen_for_test':hc,'merge_policy':cfg['merge_policy'],'sentinel_hub_pu_used':0,'thresholds_tuned':False,'product_thresholds_frozen':False,'next_step':'C5d blinded visual QA of third-holdout HIGH_CONFIDENCE_SPLIT positives and comparison cases; do not tune before reveal.'}
    (out/'c5c_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('AKERPULS PRELIM FIELDS 2026 - STOPPUNKT C5C FROZEN THIRD-HOLDOUT VALIDATION')
    print(f'PILOT_FIELDS={len(g)} ALL_VALID_PIXEL_FRACTION={summary["all_valid_pixel_fraction"]:.4f}')
    print(f'BASELINE_SPLITS={baseline_n}/{len(g)} RATE={summary["baseline_split_rate"]:.4f}')
    print(f'SPLIT_CANDIDATES={cand_n}/{len(g)} RATE={summary["split_candidate_rate"]:.4f} RETENTION={summary["candidate_retention_of_baseline"]:.4f}')
    print(f'HIGH_CONFIDENCE_SPLITS={high_n}/{len(g)} RATE={summary["high_confidence_rate"]:.4f} RETENTION_OF_CANDIDATES={summary["high_confidence_retention_of_candidates"]:.4f}')
    print(f'UNCERTAIN_FIELDS={uncertain_n}/{len(g)}')
    print(f'ADJACENCY_PAIRS={len(adj)} MERGE_CANDIDATES={merge_n} RATE={summary["merge_candidate_rate"]:.4f} POLICY={cfg["merge_policy"]}')
    print('CANDIDATE_DISCOVERY_CONTRACT=IDENTICAL_TO_B2')
    print('SPLIT_CANDIDATE_RULE_CHANGED=FALSE')
    print('HIGH_CONFIDENCE_RULE_CHANGED=FALSE')
    print('THRESHOLDS_TUNED=FALSE')
    print('PRODUCT_THRESHOLDS_FROZEN=FALSE')
    print('SENTINEL_HUB_PU_USED=0')
    print('C5C_STATUS=PASS')
    print('OUTPUT='+str(out))
    return 0

if __name__=='__main__': raise SystemExit(main())
