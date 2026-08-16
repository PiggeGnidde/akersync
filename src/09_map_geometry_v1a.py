#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json
from pathlib import Path
import geopandas as gpd
import pandas as pd

HTML = '''<!doctype html><html lang="sv"><head><meta charset="utf-8"/>
<title>ÅkerSync Geometry V1a karta</title><meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>html,body,#map{height:100%;margin:0}.panel{position:absolute;top:10px;left:10px;z-index:1000;background:#ffffffe8;padding:10px 12px;border-radius:8px;max-width:390px;font:13px Arial}.sw{display:inline-block;width:12px;height:12px;margin-right:6px;vertical-align:middle}</style>
</head><body><div class="panel"><b>ÅkerSync Geometry V1a</b><br>Visuell QA av kandidater och extrema skiftesformer.<br><br>
<div><span class="sw" style="background:#18a558"></span>Königsegg-kandidat (4/4)</div>
<div><span class="sw" style="background:#0b72ff"></span>Stark kandidat (3/4)</div>
<div><span class="sw" style="background:#f39c12"></span>Extrem / specialfall</div>
<div><span class="sw" style="background:#d81b60"></span>Svår form</div></div><div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const map=L.map('map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
const gj=__GEOJSON__;
function sty(f){const c=f.properties.map_class; const m={konigsegg:'#18a558',strong:'#0b72ff',extreme:'#f39c12',difficult:'#d81b60'}; return {color:m[c]||'#666',weight:c==='konigsegg'?3:2,fillColor:m[c]||'#666',fillOpacity:.42};}
function pop(p){return `<b>${p.kommun} · ${p.skiftesbeteckning}</b><br>Block: ${p.blockid}<br>Kategori: ${p.category}<br>Areal: ${Number(p.area_ha).toFixed(2)} ha<br>Rectangularity: ${Number(p.rectangularity).toFixed(3)}<br>Convexity: ${Number(p.convexity).toFixed(3)}<br>MBR-aspekt: ${Number(p.mbr_aspect_ratio).toFixed(3)}<br>ERL-proxy: ${Number(p.erl_proxy_m).toFixed(1)} m<br>Hål: ${p.hole_count}`;}
const layer=L.geoJSON(gj,{style:sty,onEachFeature:(f,l)=>l.bindPopup(pop(f.properties))}).addTo(map);map.fitBounds(layer.getBounds(),{padding:[20,20]});
</script></body></html>'''

def q(s,p):
    s=pd.to_numeric(s,errors='coerce').dropna()
    return float(s.quantile(p)) if len(s) else float('nan')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--geometry-csv',default='data/derived/geometry_v1a_skiften.csv')
    ap.add_argument('--skiften',default=r'C:/AkerSyncRaw/jv_skane_2025/arslager_skifte_skane_2025.gpkg')
    ap.add_argument('--out-html',default='dist/geometry_v1a_candidates_map.html')
    ap.add_argument('--out-csv',default='data/derived/geometry_v1a_candidates_map.csv')
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    geom_csv=root/a.geometry_csv if not Path(a.geometry_csv).is_absolute() else Path(a.geometry_csv)
    out_html=root/a.out_html if not Path(a.out_html).is_absolute() else Path(a.out_html)
    out_csv=root/a.out_csv if not Path(a.out_csv).is_absolute() else Path(a.out_csv)
    skiften=Path(a.skiften) if Path(a.skiften).exists() else root/a.skiften

    df=pd.read_csv(geom_csv,dtype={'blockid':str,'skiftesbeteckning':str})
    for c in ['area_ha','rectangularity','convexity','mbr_aspect_ratio','erl_proxy_m','perimeter_per_ha_m','hole_count']:
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['hole_count']=df['hole_count'].fillna(0).astype(int)
    good=df[df['geometry_valid'].fillna(False).astype(bool) & df['area_ha'].gt(0)].copy()

    p90a,p90r,p90c,p90e=(q(good[c],.90) for c in ['area_ha','rectangularity','convexity','erl_proxy_m'])
    base=good[good['area_ha']>=5].copy()
    base['hits']=((base['area_ha']>=p90a).astype(int)+(base['rectangularity']>=p90r).astype(int)+(base['convexity']>=p90c).astype(int)+(base['erl_proxy_m']>=p90e).astype(int))
    konig=base[(base['hits']>=4)&(base['hole_count']==0)].copy(); konig['category']='Königsegg-kandidat'; konig['map_class']='konigsegg'
    strong=base[(base['hits']>=3)&(base['hole_count']==0)].copy(); strong=strong[~((strong['blockid']+'|'+strong['skiftesbeteckning']).isin(konig['blockid']+'|'+konig['skiftesbeteckning']))].head(40); strong['category']='Stark kandidat'; strong['map_class']='strong'
    extreme=pd.concat([
        good.sort_values(['area_ha'],ascending=False).head(10),
        good[good['area_ha']>=1].sort_values(['rectangularity'],ascending=False).head(10),
        good[good['area_ha']>=1].sort_values(['erl_proxy_m'],ascending=False).head(10)
    ]).drop_duplicates(['blockid','skiftesbeteckning']); extreme['category']='Extrem / specialfall'; extreme['map_class']='extreme'
    difficult=pd.concat([
        good[good['area_ha']>=1].sort_values(['rectangularity','area_ha'],ascending=[True,False]).head(15),
        good[good['area_ha']>=1].sort_values(['convexity','area_ha'],ascending=[True,False]).head(15),
        good[good['area_ha']>=1].sort_values(['perimeter_per_ha_m','area_ha'],ascending=[False,False]).head(15)
    ]).drop_duplicates(['blockid','skiftesbeteckning']); difficult['category']='Svår form'; difficult['map_class']='difficult'
    sel=pd.concat([konig,strong,extreme,difficult]).drop_duplicates(['blockid','skiftesbeteckning']).copy()
    sel[['kommun','blockid','skiftesbeteckning','category','map_class','area_ha','rectangularity','convexity','mbr_aspect_ratio','erl_proxy_m','hole_count','perimeter_per_ha_m']].to_csv(out_csv,index=False,encoding='utf-8-sig')
    g=gpd.read_file(skiften)[['blockid','skiftesbeteckning','geometry']].copy(); g['blockid']=g['blockid'].astype(str); g['skiftesbeteckning']=g['skiftesbeteckning'].astype(str)
    g=g.merge(sel,on=['blockid','skiftesbeteckning'],how='inner').to_crs(4326)
    gj=json.loads(g.to_json())
    out_html.parent.mkdir(parents=True,exist_ok=True); out_html.write_text(HTML.replace('__GEOJSON__',json.dumps(gj,ensure_ascii=False)),encoding='utf-8')
    print('='*88); print('ÅkerSync · Geometry V1a · visuell kandidatkarta'); print('='*88)
    print(f'Skiften totalt:              {len(df):,}')
    print(f'Königsegg-kandidater (4/4): {len(konig):,}')
    print(f'Starka kandidater (3/4):    {len(strong):,}')
    print(f'Extremer / specialfall:     {len(extreme):,}')
    print(f'Svåra former:               {len(difficult):,}')
    print(f'Visade objekt på kartan:    {len(g):,}')
    print('Output:'); print(' ',out_html); print(' ',out_csv)
    print('V1a gör fortfarande INGEN sammansatt maskinbarhets-score.')

if __name__=='__main__':
    main()
