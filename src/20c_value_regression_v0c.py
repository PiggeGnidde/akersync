#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÅkerSync Value Regression v0c: multi-block geometry experiment."""
from __future__ import annotations
import argparse,importlib.util
from pathlib import Path
import numpy as np,pandas as pd
import value_multiblock as mb

POINT=['soil_clay_point','soil_clay_100m_mean','soil_sand_100m_mean','soil_silt_100m_mean','twi_point','twi_100m_mean','twi_100m_p90','twi_100m_p95','slope_point_deg','slope_100m_mean_deg','slope_100m_p90_deg','elev_point_m','elev_100m_mean_m','relief_100m_p95_p05_m','ln_sca_100m_p90']
GEOM=['tx_geom_rect_mean_aw','tx_geom_rect_bad20','tx_geom_bad_share_rect_lt_0p60_pct','tx_geom_effective_block_count','tx_geom_perimeter_per_ha_m','tx_geom_largest_block_share_pct']
RAW={'rect_mean_aw':'tx_geom_rect_mean_aw_raw','rect_bad20':'tx_geom_rect_bad20_raw','bad_share_lt_0p60':'tx_geom_bad_share_rect_lt_0p60_pct_raw','effective_block_count':'tx_geom_effective_block_count_raw','perimeter_per_ha':'tx_geom_perimeter_per_ha_m_raw','largest_block_share':'tx_geom_largest_block_share_pct_raw'}

def load(path,name):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def eval1(v,df,f):
    x=v.complete_subset(df,[f])
    if len(x)<12:return None
    X0,y,_=v.design(x); X1,_,_=v.design(x,[f])
    if np.linalg.matrix_rank(X1)<X1.shape[1]:return None
    p0=v.loo_predictions(X0,y);p1=v.loo_predictions(X1,y);b,_,r2,adj,_,se,pv=v.fit_ols(X1,y)
    b0=v.r2_score(y,p0);b1=v.r2_score(y,p1)
    return {'model':'baseline + '+f,'feature':f,'n':len(x),'loo_r2_baseline_same_n':b0,'loo_r2_augmented':b1,'delta_loo_r2':b1-b0,
      'train_r2_augmented':r2,'adj_r2_augmented':adj,'feature_coefficient':b[-1],'feature_std_error':se[-1],'feature_p_value':pv[-1],
      'median_abs_pct_error_loo':100*float(np.median(v.pct_error_from_log(y,p1)))}

def models(v,df,out):
    base=v.complete_subset(df,[]); X,y,names=v.design(base); beta,pred,r2,adj,rank,se,pv=v.fit_ols(X,y); loo=v.loo_predictions(X,y)
    pd.DataFrame({'term':names,'coefficient':beta,'std_error':se,'p_value':pv}).to_csv(out/'baseline_coefficients.csv',index=False,encoding='utf-8-sig')
    q=base[['sale_id','datum','akermark_ha_n','kr_per_aker_ha','lat_n','lon_n']].copy();q['observed_log_kr_per_ha']=y;q['loo_pred_log_kr_per_ha']=loo;q['observed_kr_per_ha']=np.exp(y);q['loo_pred_kr_per_ha']=np.exp(loo);q['abs_pct_error']=100*v.pct_error_from_log(y,loo);q.to_csv(out/'baseline_loo_predictions.csv',index=False,encoding='utf-8-sig')
    rows=[r for f in POINT+GEOM if f in df.columns for r in [eval1(v,df,f)] if r]; comp=pd.DataFrame(rows)
    if len(comp):comp=comp.sort_values('delta_loo_r2',ascending=False)
    comp.to_csv(out/'model_comparison.csv',index=False,encoding='utf-8-sig')
    return {'n':len(base),'names':names,'beta':beta,'r2':r2,'adj':adj,'loo':v.r2_score(y,loo),'mape':100*float(np.median(v.pct_error_from_log(y,loo))),'comp':comp}

def sensitivity(v,df,out):
    rows=[]
    for pct,flag in [(10,'tx_recon_match_10pct'),(20,'tx_recon_match_20pct'),(30,'tx_recon_match_30pct')]:
        x=df.loc[df[flag].fillna(False).astype(bool)].copy()
        for label,raw in RAW.items():
            x['_g']=pd.to_numeric(x.get(raw),errors='coerce');r=eval1(v,x,'_g')
            rows.append({'area_tolerance_pct':pct,'metric':label,'n_recon_matches':len(x),'n_model':r['n'] if r else 0,
              'loo_r2_baseline_same_n':r['loo_r2_baseline_same_n'] if r else np.nan,'loo_r2_augmented':r['loo_r2_augmented'] if r else np.nan,
              'delta_loo_r2':r['delta_loo_r2'] if r else np.nan,'feature_coefficient':r['feature_coefficient'] if r else np.nan,
              'median_abs_pct_error_loo':r['median_abs_pct_error_loo'] if r else np.nan})
    z=pd.DataFrame(rows);z.to_csv(out/'multiblock_geometry_sensitivity.csv',index=False,encoding='utf-8-sig');return z

def main():
    a=argparse.ArgumentParser();a.add_argument('--config',default='config/local_paths.json');a.add_argument('--atl');a.add_argument('--radius-m',type=float,default=100);a.add_argument('--since',default='2020-07-01');a.add_argument('--recon-radius-m',type=float,default=3000);a.add_argument('--max-link-gap-m',type=float,default=750);a.add_argument('--max-blocks',type=int,default=15);a.add_argument('--baseline-only',action='store_true');args=a.parse_args()
    root=Path(__file__).resolve().parents[1];v=load(root/'src'/'20_value_regression_v0a.py','v0a');cfg=v.load_config(root/args.config);atl=Path(args.atl or v.choose_atl_csv());since=pd.Timestamp(args.since);out=root/cfg.get('build_dir','data/derived')/'value_regression_v0c';out.mkdir(parents=True,exist_ok=True)
    print('='*88);print('ÅkerSync · Value Regression v0c · multi-block');print('='*88);print('ATL:',atl);print('Output:',out);print(f'Reconstruction: radius {args.recon_radius_m:g} m, max gap {args.max_link_gap_m:g} m, max {args.max_blocks} blocks');print('Selection uses location + sold area only; geometry is calculated afterwards.\n')
    audit,allc=v.load_and_select_clean(atl);dates=pd.to_datetime(audit.datum,errors='coerce');audit['q_v0c_date_window']=dates.ge(since);audit['selected_clean_v0c']=audit.selected_clean.fillna(False).astype(bool)&audit.q_v0c_date_window.fillna(False).astype(bool);clean=allc.loc[pd.to_datetime(allc.datum,errors='coerce').ge(since)].copy().reset_index(drop=True);audit.to_csv(out/'selection_audit.csv',index=False,encoding='utf-8-sig');clean.to_csv(out/'clean_cases.csv',index=False,encoding='utf-8-sig')
    print(f'ATL-rader: {len(pd.read_csv(atl,sep=";",encoding="utf-8-sig")):,}\nUnika transaktioner: {len(audit):,}\nRena före datumfilter: {len(allc):,}\nRena v0c-case: {len(clean):,}\n')
    e=clean.copy();members=pd.DataFrame()
    if not args.baseline_only:
        print('[1/3] Multi-block reconstruction...');e,members=mb.add_features(e,cfg,v,args.recon_radius_m,args.max_link_gap_m,args.max_blocks)
        print('[2/3] Jord punkt + 100 m...');e=v.add_soil_features(e,cfg,args.radius_m)
        print('[3/3] TWI/topografi punkt + 100 m...');e=v.add_hydro_topo_features(e,cfg,args.radius_m)
    e.to_csv(out/'point_features.csv',index=False,encoding='utf-8-sig')
    if len(members):members.to_csv(out/'multiblock_members.csv',index=False,encoding='utf-8-sig')
    cols=[c for c in ['sale_id','datum','fastighetsbeteckning','municipality_county','akermark_ha_n','tx_recon_available','tx_recon_reason','tx_recon_anchor_blockid','tx_recon_candidate_pool_n','tx_recon_block_count','tx_recon_area_ha','tx_recon_area_ratio_to_sale','tx_recon_area_abs_pct_diff','tx_recon_max_point_distance_m','tx_recon_max_link_gap_m','tx_recon_blockids','tx_recon_match_10pct','tx_recon_match_20pct','tx_recon_match_30pct']+list(RAW.values()) if c in e.columns]
    if cols:e[cols].to_csv(out/'multiblock_reconstruction.csv',index=False,encoding='utf-8-sig');sens=sensitivity(v,e,out)
    res=models(v,e,out);L=['ÅkerSync Value Regression v0c — multi-block','='*76,f'ATL source: {atl}',f'Unique transactions after dedup: {len(audit)}',f'Clean cases before date window: {len(allc)}',f'Sample start: {since.date()}',f'Clean v0c cases: {len(clean)}']
    if 'tx_recon_available' in e:
        ok=e.tx_recon_available.fillna(False).astype(bool);L += [f'Anchor block available: {int(ok.sum())}/{len(e)}']+[f'Multi-block area match ±{p}%: {int(e[f"tx_recon_match_{p}pct"].fillna(False).sum())}/{len(e)}' for p in (10,20,30)];L += [f'Median reconstruction area error: {pd.to_numeric(e.loc[ok,"tx_recon_area_abs_pct_diff"],errors="coerce").median():.1f}%',f'Median reconstructed block count: {pd.to_numeric(e.loc[ok,"tx_recon_block_count"],errors="coerce").median():.1f}']
    L += ['','RECONSTRUCTION RULE','Mandatory anchor = block containing ATL point.','Grow by nearest polygon gap; stop at sold ha / gap cap / block cap.','No shape metric participates in block selection.','Selected blocks stay separate; they are never merged for geometry scoring.','','BASELINE','log(kr/åker-ha) ~ year + log(area) + lat + lon',f'n={res["n"]}',f'R2={res["r2"]:.6f}',f'Adjusted R2={res["adj"]:.6f}',f'LOO R2={res["loo"]:.6f}',f'LOO median absolute percentage error={res["mape"]:.2f}%','','Coefficients:']+[f'  {n:18s} {b: .8f}' for n,b in zip(res['names'],res['beta'])]
    if len(res['comp']):L += ['','MODEL COMPARISON — sorted by Δ LOO R2']+[f'  {r.feature}: n={int(r.n)}, LOO={r.loo_r2_augmented:.4f}, Δ={r.delta_loo_r2:+.4f}, beta={r.feature_coefficient:+.4g}, medianAPE={r.median_abs_pct_error_loo:.1f}%' for _,r in res['comp'].iterrows()]
    L += ['','BAD20 = area-weighted rectangularity of the worst 20% of reconstructed hectares.','Reconstruction is a proximity/area proxy, not cadastral identification.','Primary metric: Δ LOO R2 versus baseline on the SAME rows.'];report='\n'.join(L)+'\n';(out/'report.txt').write_text(report,encoding='utf-8');print('\n'+report);print('Output:',out);return 0
if __name__=='__main__':raise SystemExit(main())
