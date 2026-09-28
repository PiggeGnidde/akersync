"""VT-A5 diagnostic: Hallands Väderö ↔ Bjärehalvön VISS geometry.

Read-only diagnostic. It does not modify frozen VT-A2/A3 data or the web.
Exports a small GeoPackage for visual inspection plus JSON diagnostics.
"""
from __future__ import annotations
import json
from pathlib import Path
import geopandas as gpd
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
A1C=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a1c'
A2=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a2'
A2B=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a2b'
OUT=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a5_hallands_vadero'
BLOCK='62622995454'
SKIFTE='11A'
FIELD_ID=f'{BLOCK}|{SKIFTE}'
TARGET_EU='SE625674-131386'

def loadj(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def norm(x): return '' if x is None else str(x).strip().upper()
def readvec(p): return gpd.read_parquet(p) if p.suffix.lower()=='.parquet' else gpd.read_file(p)

def geom_stats(g):
    b=g.bounds
    rp=g.representative_point()
    return {'geom_type':g.geom_type,'area_ha':float(g.area/10000),'bounds_sweref99':[float(x) for x in b],
            'representative_point_sweref99':[float(rp.x),float(rp.y)]}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    print('='*92); print('ÅkerKontext · VattenTryck — VT-A5 Hallands Väderö diagnostic'); print('='*92)
    a2=loadj(A2/'summary.json'); waters=loadj(A1C/'waters.json')
    field_source=Path(a2['field_source'])
    fields=readvec(field_source).to_crs(3006)
    fields['blockid']=fields['blockid'].astype(str); fields['skiftesbeteckning']=fields['skiftesbeteckning'].astype(str)
    f=fields[(fields.blockid==BLOCK)&(fields.skiftesbeteckning==SKIFTE)].copy()
    if len(f)!=1: raise RuntimeError(f'Expected exactly one target field, got {len(f)}')
    f['field_id']=FIELD_ID
    fg=f.geometry.iloc[0]

    gw_raw=gpd.read_file(A2/'viss_groundwater_all.geojson').to_crs(3006)
    lookup={str(c).upper():c for c in gw_raw.columns}; eucol=lookup.get('EU_CD') or lookup.get('VISS_EU_CD')
    if not eucol: raise RuntimeError('No EU_CD column')
    gw_raw['EU_CD_N']=gw_raw[eucol].map(norm)
    gw=gw_raw.dissolve(by='EU_CD_N',as_index=False)[['EU_CD_N','geometry']]

    # Every GW geometry with true positive-area overlap with the island field.
    cand=gw[gw.intersects(fg)].copy()
    cand['overlap_m2']=cand.geometry.map(lambda g:g.intersection(fg).area)
    cand=cand[cand.overlap_m2>0].copy()
    cand['overlap_fraction']=cand.overlap_m2/fg.area

    rel=pd.read_parquet(A2B/'field_case_overlap_relations.parquet')
    rel_target=rel[rel.field_id.astype(str)==FIELD_ID].copy()
    dom=pd.read_parquet(A2B/'field_dominant_case.parquet')
    dom_target=dom[dom.field_id.astype(str)==FIELD_ID].copy()

    target=gw[gw.EU_CD_N==TARGET_EU].copy()
    if len(target)!=1: raise RuntimeError(f'Expected one dissolved {TARGET_EU}, got {len(target)}')
    tg=target.geometry.iloc[0]
    inter=fg.intersection(tg)
    water_name={norm(w.get('EU_CD')):str(w.get('Name') or w.get('EU_CD')) for w in waters}

    print(f'Target field:                         {FIELD_ID}')
    print(f'Field area:                           {fg.area/10000:.4f} ha')
    print(f'All dissolved GW bodies overlapping: {len(cand):,}')
    if len(cand):
        show=cand[['EU_CD_N','overlap_m2','overlap_fraction']].copy(); show['name']=show.EU_CD_N.map(water_name)
        print(show.sort_values('overlap_fraction',ascending=False).to_string(index=False))
    print('\nFROZEN VT-A2b RELATIONS FOR FIELD')
    print('-'*92)
    print(rel_target.to_string(index=False) if len(rel_target) else 'NONE')
    print('\nFROZEN VT-A2b DOMINANT')
    print('-'*92)
    print(dom_target.to_string(index=False) if len(dom_target) else 'NONE')
    print('\nBJÄREHALVÖN GEOMETRY')
    print('-'*92)
    print(f'Name:                                 {water_name.get(TARGET_EU,TARGET_EU)}')
    print(f'Geometry type:                        {tg.geom_type}')
    print(f'Dissolved area:                       {tg.area/1e6:.3f} km²')
    print(f'Number of polygon parts:              {len(tg.geoms) if tg.geom_type=="MultiPolygon" else 1}')
    print(f'Bounds SWEREF99:                      {tuple(round(x,1) for x in tg.bounds)}')
    print(f'Field overlap with Bjärehalvön:       {inter.area/10000:.4f} ha ({100*inter.area/fg.area:.2f}%)')
    print(f'Field representative point in body:   {tg.covers(fg.representative_point())}')

    # Export only diagnostic geometry. GPKG layers can be opened in QGIS if desired.
    gpkg=OUT/'hallands_vadero_bjarehalvon_diagnostic.gpkg'
    if gpkg.exists(): gpkg.unlink()
    f[['field_id','geometry']].to_file(gpkg,layer='target_field',driver='GPKG')
    target.assign(name=water_name.get(TARGET_EU,TARGET_EU)).to_file(gpkg,layer='bjarehalvon_viss_gw',driver='GPKG')
    if not inter.is_empty:
        gpd.GeoDataFrame([{'field_id':FIELD_ID,'EU_CD':TARGET_EU,'geometry':inter}],crs=3006).to_file(gpkg,layer='intersection',driver='GPKG')
    if len(cand): cand.assign(name=cand.EU_CD_N.map(water_name)).to_file(gpkg,layer='all_overlapping_gw',driver='GPKG')

    result={'target_field':FIELD_ID,'target_eu_cd':TARGET_EU,'target_name':water_name.get(TARGET_EU,TARGET_EU),
            'field':geom_stats(fg),'bjarehalvon':geom_stats(tg),'overlap_ha':float(inter.area/10000),
            'overlap_fraction':float(inter.area/fg.area),'representative_point_inside':bool(tg.covers(fg.representative_point())),
            'all_overlapping_groundwater_bodies':[{'EU_CD':r.EU_CD_N,'name':water_name.get(r.EU_CD_N,r.EU_CD_N),'overlap_fraction':float(r.overlap_fraction)} for r in cand.itertuples()],
            'frozen_a2b_relations':rel_target.to_dict(orient='records'),'frozen_a2b_dominant':dom_target.to_dict(orient='records')}
    (OUT/'diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('\nSaved: '+str(OUT.relative_to(ROOT)).replace('\\','/'))
    print('  diagnostic.json')
    print('  hallands_vadero_bjarehalvon_diagnostic.gpkg')
    print('VT-A5 DIAGNOSTIC COMPLETE — NO DATA OR UI MODIFIED')
    print('='*92)
if __name__=='__main__': main()
