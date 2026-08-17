#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nearby-block transaction reconstruction for ÅkerSync Value Regression.

Selection uses location/proximity + sold hectares only. Shape metrics are
computed only after the selected block set is locked, preventing circular
selection on the geometry variables later tested in the price regression.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from shapely.ops import unary_union

BAD_TAIL_SHARE = 0.20
BAD_RECT_THRESHOLD = 0.60


def finite(v):
    try: x=float(v)
    except Exception: return np.nan
    return x if np.isfinite(x) else np.nan


def bad_tail_mean(areas, vals, share=BAD_TAIL_SHARE):
    pairs=[(finite(v),finite(a)) for a,v in zip(areas,vals)]
    pairs=[(v,a) for v,a in pairs if np.isfinite(v) and np.isfinite(a) and a>0]
    if not pairs:return np.nan
    target=share*sum(a for _,a in pairs); remain=target; num=0.0
    for v,a in sorted(pairs):
        take=min(a,remain); num+=take*v; remain-=take
        if remain<=1e-12:break
    used=target-max(0.0,remain)
    return num/used if used>0 else np.nan


def tx_geometry(members):
    if not members:return {}
    a=np.array([finite(r['block_area_ha']) for r in members])
    r=np.array([finite(r['rectangularity']) for r in members])
    p=np.array([finite(r['perimeter_m']) for r in members])
    oka=np.isfinite(a)&(a>0); total=float(a[oka].sum()) if oka.any() else np.nan
    if not np.isfinite(total) or total<=0:return {}
    okr=oka&np.isfinite(r)
    mean=float((a[okr]*r[okr]).sum()/a[okr].sum()) if okr.any() else np.nan
    bad20=bad_tail_mean(a[okr],r[okr]) if okr.any() else np.nan
    bad_area=float(a[okr&(r<BAD_RECT_THRESHOLD)].sum()) if okr.any() else np.nan
    shares=a[oka]/total
    perim=float(p[oka&np.isfinite(p)].sum()) if np.any(oka&np.isfinite(p)) else np.nan
    return {
      'tx_geom_rect_mean_aw_raw':mean,
      'tx_geom_rect_bad20_raw':bad20,
      'tx_geom_bad_share_rect_lt_0p60_pct_raw':100*bad_area/total if np.isfinite(bad_area) else np.nan,
      'tx_geom_effective_block_count_raw':float(1/(shares*shares).sum()),
      'tx_geom_perimeter_per_ha_m_raw':perim/total if np.isfinite(perim) else np.nan,
      'tx_geom_largest_block_share_pct_raw':100*float(shares.max()),
    }


def nearby_indices(blocks,point,radius):
    q=point.buffer(radius)
    try: x=blocks.sindex.query(q,predicate='intersects')
    except Exception: x=blocks.sindex.query(q)
    return sorted(set(int(i) for i in x))


def reconstruct_one(blocks,point,sold_ha,v0a,radius=3000.0,max_gap=750.0,max_blocks=15):
    anchor=v0a.containing_row(blocks,point); sold=finite(sold_ha)
    if anchor is None:return {'tx_recon_available':False,'tx_recon_reason':'ATL_point_outside_2025_block'},[]
    if not np.isfinite(sold) or sold<=0:return {'tx_recon_available':False,'tx_recon_reason':'invalid_sold_area'},[]
    ai=int(anchor.name); pool=nearby_indices(blocks,point,radius)
    if ai not in pool:pool.append(ai)
    info={}
    for i in sorted(set(pool)):
        row=blocks.iloc[i]; g=row.geometry
        if g is None or g.is_empty or g.area<=0:continue
        info[i]={'blockid':str(row.get('blockid',i)),'g':g,'area':float(g.area)/10000,'dist':float(g.distance(point))}
    if ai not in info:return {'tx_recon_available':False,'tx_recon_reason':'anchor_geometry_invalid'},[]

    selected=[ai]; gaps={ai:0.0}; cum=[info[ai]['area']]; maxdist=[info[ai]['dist']]; maxg=[0.0]; cluster=info[ai]['g']
    while len(selected)<max_blocks and cum[-1]<sold:
        rem=[i for i in info if i not in selected]
        if not rem:break
        ranked=[(float(cluster.distance(info[i]['g'])),info[i]['dist'],info[i]['blockid'],i) for i in rem]
        gap,_,_,nxt=min(ranked)
        if gap>max_gap:break
        selected.append(nxt); gaps[nxt]=gap
        cum.append(cum[-1]+info[nxt]['area']); maxdist.append(max(maxdist[-1],info[nxt]['dist'])); maxg.append(max(maxg[-1],gap))
        cluster=unary_union([cluster,info[nxt]['g']])

    # Only proximity-growth prefixes are eligible: no arbitrary subset-sum fishing.
    best=min(range(len(cum)),key=lambda j:(abs(cum[j]/sold-1),maxdist[j],j+1)); chosen=selected[:best+1]
    members=[]; running=0.0
    for order,i in enumerate(chosen,1):
        z=info[i]; running+=z['area']; gm=v0a.geometry_metrics(z['g'])
        members.append({'order':order,'blockid':z['blockid'],'block_area_ha':z['area'],'point_distance_m':z['dist'],
          'link_gap_m':gaps.get(i,0.0),'cumulative_area_ha':running,'rectangularity':gm.get('geom_rectangularity',np.nan),
          'convexity':gm.get('geom_convexity',np.nan),'compactness':gm.get('geom_compactness',np.nan),
          'mbr_aspect':gm.get('geom_mbr_aspect',np.nan),'perimeter_m':float(z['g'].length)})
    area=sum(x['block_area_ha'] for x in members); err=100*abs(area/sold-1)
    out={'tx_recon_available':True,'tx_recon_reason':'OK','tx_recon_anchor_blockid':info[ai]['blockid'],
      'tx_recon_candidate_pool_n':len(info),'tx_recon_block_count':len(members),'tx_recon_area_ha':area,
      'tx_recon_area_ratio_to_sale':area/sold,'tx_recon_area_abs_pct_diff':err,
      'tx_recon_max_point_distance_m':max(x['point_distance_m'] for x in members),
      'tx_recon_max_link_gap_m':max(x['link_gap_m'] for x in members),
      'tx_recon_blockids':' | '.join(x['blockid'] for x in members),
      'tx_recon_match_10pct':err<=10,'tx_recon_match_20pct':err<=20,'tx_recon_match_30pct':err<=30}
    out.update(tx_geometry(members)); return out,members


def add_features(clean,cfg,v0a,radius=3000.0,max_gap=750.0,max_blocks=15):
    p=Path(cfg.get('blocks',''))
    if not p.exists():raise FileNotFoundError(f'Blockfil saknas: {p}')
    blocks=gpd.read_file(p).to_crs(3006).reset_index(drop=True); blocks['blockid']=blocks.blockid.astype(str)
    pts=gpd.GeoDataFrame(clean[['sale_id']].copy(),geometry=gpd.points_from_xy(clean.lon_n,clean.lat_n),crs=4326).to_crs(3006)
    summaries=[]; all_members=[]
    for i,point in enumerate(pts.geometry):
        s,m=reconstruct_one(blocks,point,clean.at[i,'akermark_ha_n'],v0a,radius,max_gap,max_blocks); s['sale_id']=clean.at[i,'sale_id']; summaries.append(s)
        for x in m: x=dict(x); x['sale_id']=clean.at[i,'sale_id']; all_members.append(x)
        if (i+1)%10==0 or i+1==len(pts):print(f'\rMulti-block {i+1}/{len(pts)}',end='',flush=True)
    print()
    out=clean.merge(pd.DataFrame(summaries),on='sale_id',how='left',validate='one_to_one')
    ok=out.tx_recon_match_20pct.fillna(False).astype(bool)
    mapping={'tx_geom_rect_mean_aw_raw':'tx_geom_rect_mean_aw','tx_geom_rect_bad20_raw':'tx_geom_rect_bad20',
      'tx_geom_bad_share_rect_lt_0p60_pct_raw':'tx_geom_bad_share_rect_lt_0p60_pct',
      'tx_geom_effective_block_count_raw':'tx_geom_effective_block_count','tx_geom_perimeter_per_ha_m_raw':'tx_geom_perimeter_per_ha_m',
      'tx_geom_largest_block_share_pct_raw':'tx_geom_largest_block_share_pct'}
    for raw,main in mapping.items():out[main]=np.where(ok,pd.to_numeric(out.get(raw),errors='coerce'),np.nan)
    return out,pd.DataFrame(all_members)
