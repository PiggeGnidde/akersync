#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D3 — local interactive map for ÅkerFrö × ÅkerAccess ranking sanity check.

Builds one HTML file with inline field GeoJSON and Leaflet loaded from CDN.
No API keys. OSM basemap tiles are loaded by the browser.

The map contains the union of top-N fields from three D2 rankings so the user
can switch ranking and list depth without rebuilding.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import webbrowser
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT,ROOT/"src"):
    if str(p) not in sys.path:
        sys.path.insert(0,str(p))

from analysis.akeraccess_v0a.entry_discovery_v0a import discover_field_inputs
from analysis.akeraccess_v0a.skane_road_features_d0 import load_skane_fields
from analysis.akeraccess_v0a.skane_pea_replication_d1 import load_history

DEFAULT_D2=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d2"/"akerfro_akeraccess_d2_fields.parquet"
DEFAULT_D4=ROOT/"work"/"akeraccess_v0a"/"bjuv_route_d4"/"bestmatch_d4_fields.parquet"
DEFAULT_OUT=ROOT/"work"/"akeraccess_v0a"/"bestmatch_d3_map"
DEFAULT_AKERMINNE=Path(r"C:\AkerSync-Minne")
RANKINGS={
    "Balanced BestMatch":"rank_bestmatch_balanced",
    "Frozen C10 baseline":"rank_c10_baseline",
    "Access-first":"rank_access_first",
}
TOP_CHOICES=[200,500,800,1000,2000,5000]


def norm_id(x):
    if x is None:
        return ""
    s=str(x).strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    return s


def build_geojson(d2:pd.DataFrame,nmax:int,akerminne_root:Path)->dict:
    ids=set()
    for col in RANKINGS.values():
        q=d2[pd.to_numeric(d2[col],errors="coerce").notna()].copy()
        q[col]=pd.to_numeric(q[col],errors="coerce")
        ids.update(q.nsmallest(min(nmax,len(q)),col)["field_id"].astype(str))

    d=d2[d2["field_id"].astype(str).isin(ids)].copy()

    # Attach ÅkerMinne crop history only for the displayed union, keeping D3
    # useful as a field sanity-check tool without loading history into D2.
    hist,_sources=load_history(akerminne_root,set(ids))
    hist=hist.copy()
    hist["history_year"]=pd.to_numeric(hist["history_year"],errors="coerce").astype("Int64")
    hist["crop_label"]=hist["dominant_crop_name"].fillna("").astype(str)
    hist["status_label"]=hist["status"].fillna("").astype(str)
    rows=[]
    for fid,g in hist.groupby("field_id",sort=False):
        g=g.sort_values("history_year",kind="mergesort")
        by_year={}
        parts=[]
        for r in g.itertuples(index=False):
            if pd.isna(r.history_year):
                continue
            y=int(r.history_year)
            crop=str(r.crop_label).strip() or "—"
            by_year[y]=crop
            parts.append(f"{y}: {crop}")
        rows.append({
            "field_id":str(fid),
            "akerminne_2022":by_year.get(2022,"—"),
            "akerminne_2023":by_year.get(2023,"—"),
            "akerminne_2024":by_year.get(2024,"—"),
            "akerminne_2025":by_year.get(2025,"—"),
            "akerminne_history":" | ".join(parts),
        })
    if rows:
        d=d.merge(pd.DataFrame(rows),on="field_id",how="left",validate="one_to_one")

    blocks_path,skiften_path,_local_cfg=discover_field_inputs()
    geom=load_skane_fields(blocks_path,skiften_path)
    geom["field_id"]=geom["field_id"].map(norm_id)
    geom=geom[geom["field_id"].isin(ids)][["field_id","geometry"]].copy()
    if geom["field_id"].duplicated().any():
        raise RuntimeError("Current field geometry duplicate")

    g=geom.merge(d,on="field_id",how="inner",validate="one_to_one")
    g=gpd.GeoDataFrame(g,geometry="geometry",crs=3006).to_crs(4326)
    g["geometry"]=g.geometry.simplify(0.000015,preserve_topology=True)

    props=[
        "field_id","municipality","field_area_ha","artkandidat_class",
        "artmatch_score","area_logistics_score","road_access_score",
        "bestmatch_balanced_score","rank_c10_baseline","rank_access_first",
        "rank_bestmatch_balanced","nearest_drivable_osm_m",
        "nearest_statlig_kommunal_nvdb_m","network_access_status",
        "rotation_status","predecessor_prior","distance_bjuv_km",
        "field_to_bjuv_road_km","bjuv_route_status","bjuv_road_vs_straight_factor",
        "historical_conservart_positive",
        "akerminne_2022","akerminne_2023","akerminne_2024","akerminne_2025",
        "akerminne_history",
    ]
    props=[c for c in props if c in g.columns]
    gg=g[props+["geometry"]].copy()
    for c in props:
        if c.startswith("rank_"):
            gg[c]=pd.to_numeric(gg[c],errors="coerce").astype("Int64")
    return json.loads(gg.to_json(drop_id=True))


HTML_HEAD="""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>ÅkerFrö × ÅkerAccess — BestMatch D3</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
html,body,#map{height:100%;margin:0}
body{font-family:Arial,Helvetica,sans-serif}
.panel{position:absolute;z-index:1000;top:12px;left:12px;background:white;padding:12px 14px;
 border-radius:8px;box-shadow:0 1px 7px rgba(0,0,0,.35);max-width:360px}
.panel h3{margin:0 0 8px 0;font-size:17px}
.panel label{display:block;margin:5px 0}
.panel select{width:100%;padding:4px}
.legend{margin-top:8px;font-size:12px;line-height:1.35}
.badge{display:inline-block;padding:2px 6px;border-radius:10px;background:#eee;margin-right:4px}
.leaflet-popup-content{min-width:270px}
.small{font-size:11px;color:#555}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
<h3>ÅkerFrö × ÅkerAccess</h3>
<label>Ranking
<select id="ranking">
<option value="rank_bestmatch_balanced">Balanced BestMatch</option>
<option value="rank_c10_baseline">Frozen C10 baseline</option>
<option value="rank_access_first">Access-first</option>
</select></label>
<label>Visa topp
<select id="topn">
<option>200</option><option>500</option><option selected>800</option>
<option>1000</option><option>2000</option><option>5000</option>
</select></label>
<label><input type="checkbox" id="onlyA"> endast A_STRONG_CANDIDATE</label>
<button id="zoomSelection" style="width:100%;margin-top:6px;padding:5px">Zooma till valt urval</button>
<div id="stats" class="legend"></div>
<div id="pinned" class="legend"></div>
<div class="legend">
  <b>Färg = ranking inom valt urval</b>
  <div style="height:12px;border:1px solid #777;border-radius:3px;
       background:linear-gradient(90deg,hsl(115,75%,45%),hsl(72,75%,45%),hsl(30,75%,45%));
       margin:4px 0 2px 0"></div>
  <div style="display:flex;justify-content:space-between">
    <span>Bäst rank</span><span>Lägst rank i urvalet</span>
  </div>
</div>
<div class="small">Grönt = högst rankad. Gult/orange = längre ned i den valda topplistan. Klicka ett fält för detaljer.</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
"""

HTML_TAIL=r"""
const map=L.map('map').setView([55.95,13.35],9);

// Local file:// viewers can trigger blocking / API-key requirements on
// some public basemap providers. Use ArcGIS public tile services as default.
// These endpoints require no project API key for this local MVP viewer.
const esriImagery=L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {
    maxZoom:19,
    attribution:'Tiles &copy; Esri'
  }
).addTo(map);

const esriStreet=L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
  {
    maxZoom:19,
    attribution:'Tiles &copy; Esri'
  }
);

const esriTopo=L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
  {
    maxZoom:19,
    attribution:'Tiles &copy; Esri'
  }
);

L.control.layers(
  {
    'Satellit (Esri)':esriImagery,
    'Vägkarta (Esri)':esriStreet,
    'Topo (Esri)':esriTopo
  },
  {},
  {position:'bottomright'}
).addTo(map);

let layer=null;
let firstRender=true;
let selectedFieldId=null;
function esc(x){return String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function num(x,d=1){const n=Number(x); return Number.isFinite(n)?n.toFixed(d):'—';}
function fillFor(rank,topn){
  const t=Math.min(1,Math.max(0,(Number(rank)-1)/Math.max(1,topn-1)));
  const hue=115-85*t;
  return 'hsl('+hue+',75%,45%)';
}
function popup(p,rankCol){
  return '<b>'+esc(p.field_id)+'</b><br>'+
  esc(p.municipality)+' · '+num(p.field_area_ha,1)+' ha<br>'+
  '<span class="badge">'+esc(p.artkandidat_class)+'</span><hr>'+
  '<b>Ranker</b><br>'+
  'Balanced: <b>'+esc(p.rank_bestmatch_balanced??'—')+'</b><br>'+
  'C10 baseline: <b>'+esc(p.rank_c10_baseline??'—')+'</b><br>'+
  'Access-first: <b>'+esc(p.rank_access_first??'—')+'</b><hr>'+
  'ÄrtMatch: <b>'+num(p.artmatch_score,1)+'</b><br>'+
  'AreaLogistik: <b>'+num(p.area_logistics_score,1)+'</b><br>'+
  'Väglogistik: <b>'+num(p.road_access_score,1)+'</b><br>'+
  'BestMatch: <b>'+num(p.bestmatch_balanced_score,1)+'</b><br>'+
  'Till närmaste körbara väg: <b>'+num(p.nearest_drivable_osm_m,1)+' m</b><br>'+
  'Till statlig/kommunal väg: <b>'+num(p.nearest_statlig_kommunal_nvdb_m,1)+' m</b><br>'+
  (Number.isFinite(Number(p.field_to_bjuv_road_km))
    ? 'Vägavstånd till Bjuv: <b>'+num(p.field_to_bjuv_road_km,1)+' km</b><br>'+
      '<span class="small">Fågelväg: '+num(p.distance_bjuv_km,1)+' km</span><br>'
    : 'Till Bjuv (fågelväg): '+num(p.distance_bjuv_km,1)+' km<br>')+
  'Rotation: '+esc(p.rotation_status)+'<br>'+
  'Förfrukt: '+esc(p.predecessor_prior)+'<br>'+
  'Historisk conservärt: '+(p.historical_conservart_positive?'ja':'nej')+'<hr>'+
  '<b>ÅkerMinne</b><br>'+
  '2022: <b>'+esc(p.akerminne_2022??'—')+'</b><br>'+
  '2023: '+esc(p.akerminne_2023??'—')+'<br>'+
  '2024: '+esc(p.akerminne_2024??'—')+'<br>'+
  '2025: '+esc(p.akerminne_2025??'—')+'<br>'+
  '<span class="small">'+esc(p.akerminne_history??'')+'</span>';
}
function render(){
  const rankCol=document.getElementById('ranking').value;
  const topn=Number(document.getElementById('topn').value);
  const onlyA=document.getElementById('onlyA').checked;
  if(layer) map.removeLayer(layer);
  let n=0,ha=0,apos=0,hist=0;
  layer=L.geoJSON(FIELDS,{
    filter:f=>{
      const p=f.properties, r=Number(p[rankCol]);
      const inTop=Number.isFinite(r)&&r<=topn&&(!onlyA||p.artkandidat_class==='A_STRONG_CANDIDATE');
      const pinned=(selectedFieldId!==null && p.field_id===selectedFieldId);
      return inTop||pinned;
    },
    style:f=>{
      const r=Number(f.properties[rankCol]);
      const pinned=(selectedFieldId!==null && f.properties.field_id===selectedFieldId);
      if(pinned){
        return {color:'#000',weight:4,fillColor:fillFor(r,topn),fillOpacity:.82,dashArray:'6 4'};
      }
      return {color:'#333',weight:.6,fillColor:fillFor(r,topn),fillOpacity:.62};
    },
    onEachFeature:(f,l)=>{
      const p=f.properties;
      const rr=Number(p[rankCol]);
      const inTop=Number.isFinite(rr)&&rr<=topn&&(!onlyA||p.artkandidat_class==='A_STRONG_CANDIDATE');
      if(inTop){
        n++; ha+=Number(p.field_area_ha)||0;
        if(p.artkandidat_class==='A_STRONG_CANDIDATE') apos++;
        if(p.historical_conservart_positive) hist++;
      }
      l.bindPopup(popup(p,rankCol));
      l.on('click',()=>{
        selectedFieldId=p.field_id;
        document.getElementById('pinned').innerHTML=
          '<b>Valt fält:</b> '+esc(p.field_id)+' · växla ranking för att följa samma fält';
      });
    }
  }).addTo(map);
  document.getElementById('stats').innerHTML=
    '<b>'+n.toLocaleString('sv-SE')+'</b> fält · <b>'+ha.toFixed(0)+'</b> ha<br>'+
    'A-klass '+apos.toLocaleString('sv-SE')+' · historisk conservärt '+hist;
  if(selectedFieldId!==null){
    layer.eachLayer(l=>{
      const p=l.feature&&l.feature.properties;
      if(p&&p.field_id===selectedFieldId){
        l.setStyle({color:'#000',weight:4,dashArray:'6 4',fillOpacity:.82});
        l.bindPopup(popup(p,rankCol));
      }
    });
  }
  // Fit only on initial page load. Changing ranking/top-N must preserve the
  // current pan/zoom so the user can compare exactly the same local area.
  if(firstRender && layer.getBounds().isValid()){
    map.fitBounds(layer.getBounds(),{padding:[20,20]});
    firstRender=false;
  }
}
function zoomToSelection(){
  if(layer && layer.getBounds().isValid()){
    map.fitBounds(layer.getBounds(),{padding:[20,20]});
  }
}
document.getElementById('pinned').addEventListener('click',()=>{
  selectedFieldId=null;
  document.getElementById('pinned').innerHTML='';
  render();
});
document.getElementById('ranking').addEventListener('change',render);
document.getElementById('topn').addEventListener('change',render);
document.getElementById('onlyA').addEventListener('change',render);
document.getElementById('zoomSelection').addEventListener('click',zoomToSelection);
render();
</script>
</body>
</html>
"""


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--d2",default=str(DEFAULT_D2))
    ap.add_argument("--out",default=str(DEFAULT_OUT))
    ap.add_argument("--akerminne-root",default=str(DEFAULT_AKERMINNE))
    ap.add_argument("--no-open",action="store_true")
    args=ap.parse_args()

    d2_path=Path(args.d2)
    source_path=DEFAULT_D4 if DEFAULT_D4.exists() and d2_path==DEFAULT_D2 else d2_path
    if not source_path.exists():
        raise FileNotFoundError(f"Run D2 first: {source_path}")
    print(f"Map source: {source_path}")
    d2=pd.read_parquet(source_path)
    d2["field_id"]=d2["field_id"].map(norm_id)
    missing=[c for c in RANKINGS.values() if c not in d2.columns]
    if missing:
        raise RuntimeError("D2 missing ranking columns: "+", ".join(missing))

    print("="*112)
    print("ÅkerFrö × ÅkerAccess D3 - INTERACTIVE MAP")
    print("="*112)
    print("Building union of top 5,000 from baseline / access-first / balanced...")
    gj=build_geojson(d2,max(TOP_CHOICES),Path(args.akerminne_root))
    print(f"Unique mapped fields in union: {len(gj.get('features',[])):,}")

    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    data_path=out/"bestmatch_d3_union_top5000.geojson"
    data_path.write_text(json.dumps(gj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")

    html=HTML_HEAD+"const FIELDS="+json.dumps(gj,ensure_ascii=False,separators=(",",":"))+";\n"+HTML_TAIL
    html_path=out/"bestmatch_d3_map.html"
    html_path.write_text(html,encoding="utf-8")

    report={
      "schema_version":"akerfro-akeraccess-bestmatch-d3-map-v0a",
      "source":str(source_path),
      "rankings":RANKINGS,
      "top_choices":TOP_CHOICES,
      "unique_fields_in_union":len(gj.get("features",[])),
      "html":str(html_path),
      "geojson":str(data_path),
      "purpose":"visual sanity check before freezing BestMatch weights or starting ÅkerKombinatorik"
    }
    rp=out/"bestmatch_d3_report.json"
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print(f"HTML: {html_path}")
    print(f"GeoJSON: {data_path}")
    print(f"Report: {rp}")
    print("="*112)
    print("ÅkerFrö × ÅkerAccess D3 MAP: PASS")
    print("="*112)
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())
    return 0


if __name__=="__main__":
    raise SystemExit(main())
