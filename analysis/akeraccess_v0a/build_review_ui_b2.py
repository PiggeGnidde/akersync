#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build ÅkerAccess STOPPUNKT B2 reviewer from prepared sample."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK = ROOT / "work" / "akeraccess_v0a" / "sjobo"
DEFAULT_OSM = ROOT / "data" / "raw" / "akeraccess_osm" / "sjobo_roads_gates.json"

LABELS = [
    ("RANK1_PLAUSIBLE", "RÖD #1 plausibel"),
    ("OTHER_CANDIDATE_BETTER", "ANNAN kandidat bättre/plausibel"),
    ("ACCESS_VISIBLE_NOT_CANDIDATE", "TYDLIG infart men ingen kandidat träffar"),
    ("NO_VISIBLE_ACCESS", "INGEN tydlig infart"),
    ("UNCLEAR", "OKLART"),
    ("EXCLUDE_OTHER", "EXKLUDERA / ej relevant fält"),
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def feature_map(geojson: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for feature in geojson.get("features", []):
        fid = str((feature.get("properties") or {}).get("field_id", ""))
        if fid:
            result[fid] = feature
    return result


def build_payload(work: Path, osm_path: Path) -> dict[str, Any]:
    review = work / "review_b2"
    sample_path = review / "sjobo_review_b2_sample.csv"
    fields_path = review / "sjobo_review_b2_fields.geojson"
    cand_path = work / "sjobo_entry_candidates.geojson"
    for p in (sample_path, fields_path, cand_path, osm_path):
        if not p.exists():
            raise FileNotFoundError(p)

    sample = load_csv(sample_path)
    sample_ids = [str(r["field_id"]) for r in sample]
    sample_set = set(sample_ids)
    fields = feature_map(load_json(fields_path))
    missing = [x for x in sample_ids if x not in fields]
    if missing:
        raise RuntimeError(f"{len(missing)} B2 sample fields missing geometry")

    candidates_by_field: dict[str, list[dict[str, Any]]] = {fid: [] for fid in sample_ids}
    way_ids: set[int] = set()
    gate_ids: set[int] = set()
    for ft in load_json(cand_path).get("features", []):
        props = ft.get("properties") or {}
        fid = str(props.get("field_id", ""))
        if fid not in sample_set:
            continue
        candidates_by_field[fid].append(ft)
        try:
            way_ids.add(int(props.get("osm_way_id")))
        except Exception:
            pass
        for token in str(props.get("gate_ids") or "").split(";"):
            if token.strip().isdigit():
                gate_ids.add(int(token.strip()))
    for fid in sample_ids:
        candidates_by_field[fid].sort(
            key=lambda f: (
                int((f.get("properties") or {}).get("candidate_rank") or 999999),
                -float((f.get("properties") or {}).get("confidence") or 0),
            )
        )

    osm = load_json(osm_path)
    nodes = {}
    node_tags = {}
    ways = {}
    for el in osm.get("elements", []):
        if el.get("type") == "node" and "id" in el and "lon" in el and "lat" in el:
            nid = int(el["id"])
            nodes[nid] = (float(el["lon"]), float(el["lat"]))
            node_tags[nid] = dict(el.get("tags") or {})
        elif el.get("type") == "way" and "id" in el:
            wid = int(el["id"])
            if wid in way_ids:
                ways[wid] = el

    road_features = []
    for wid in sorted(way_ids):
        el = ways.get(wid)
        if not el:
            continue
        coords = [nodes[int(n)] for n in el.get("nodes", []) if int(n) in nodes]
        if len(coords) < 2:
            continue
        tags = el.get("tags") or {}
        road_features.append({
            "type": "Feature",
            "properties": {
                "osm_way_id": wid,
                **{k: v for k, v in tags.items() if k in {
                    "highway", "surface", "tracktype", "smoothness", "width",
                    "maxwidth", "maxheight", "access", "service",
                }},
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    gate_features = []
    for nid in sorted(gate_ids):
        if nid not in nodes:
            continue
        tags = node_tags.get(nid, {})
        gate_features.append({
            "type": "Feature",
            "properties": {
                "osm_node_id": nid,
                **{k: v for k, v in tags.items() if k in {"barrier", "access", "width", "maxwidth"}},
            },
            "geometry": {"type": "Point", "coordinates": list(nodes[nid])},
        })

    items = []
    for row in sample:
        fid = str(row["field_id"])
        items.append({
            "review_index_b2": int(row["review_index_b2"]),
            "field_id": fid,
            "entry_status": row.get("entry_status", ""),
            "best_confidence": row.get("best_confidence", ""),
            "area_ha": row.get("area_ha", ""),
            "crop2025_name": row.get("crop2025_name", ""),
            "sample_source": row.get("sample_source", ""),
            "needs_review_b2": str(row.get("needs_review_b2", "")).casefold() in {"true", "1", "yes"},
            "initial_label": row.get("initial_label", ""),
            "mapping_basis": row.get("mapping_basis", ""),
            "legacy_label": row.get("legacy_label", ""),
            "legacy_note": row.get("legacy_note", ""),
            "field": fields[fid],
            "candidates": candidates_by_field[fid],
        })

    return {
        "items": items,
        "roads": {"type": "FeatureCollection", "features": road_features},
        "gates": {"type": "FeatureCollection", "features": gate_features},
        "labels": [{"value": v, "text": t} for v, t in LABELS],
    }


def build_html(payload: dict[str, Any]) -> str:
    data = js_json(payload)
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerAccess STOPPUNKT B2 – visual QA</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body{{height:100%;margin:0;font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
#app{{height:100%;display:grid;grid-template-columns:360px 1fr}}
#panel{{padding:12px;overflow:auto;border-right:1px solid #bbb;background:#fff}}
#map{{height:100%}}
h1{{font-size:19px;margin:0 0 6px}} h3{{margin:14px 0 6px}}
.small{{font-size:12px;color:#555}} .stat{{font-size:14px;margin:6px 0}}
.badge{{display:inline-block;padding:3px 7px;border-radius:999px;background:#eee;font-size:12px}}
.source{{font-size:12px;font-weight:700}}
button{{font-size:14px;padding:8px 9px;margin:3px 1px;cursor:pointer}}
button.label{{display:block;width:100%;text-align:left}}
button.active{{outline:3px solid #111}}
textarea{{width:100%;min-height:64px;box-sizing:border-box}}
.legend{{font-size:12px;line-height:1.5;border:1px solid #ddd;padding:7px;margin:8px 0;background:#fafafa}}
.swatch{{display:inline-block;width:22px;height:4px;margin-right:7px;vertical-align:middle}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 13px 0 6px;vertical-align:middle}}
.cand{{border-top:1px solid #ddd;padding:7px 0;font-size:12px}}
.legacy{{background:#fff8dd;border:1px solid #ead58c;padding:7px;font-size:12px;margin:7px 0}}
.topup{{background:#e9f7ee;border:1px solid #a6d8b6;padding:7px;font-size:12px;margin:7px 0}}
.kbd{{font-family:monospace;background:#eee;padding:1px 4px;border-radius:3px}}
@media(max-width:800px){{#app{{grid-template-columns:1fr;grid-template-rows:46% 54%}}#panel{{border-right:0;border-bottom:1px solid #bbb}}}}
</style>
</head>
<body>
<div id="app"><div id="panel">
<h1>ÅkerAccess STOPPUNKT B2</h1>
<div class="small">≥1 ha · betesmark/slåtteräng bort · gammal QA återanvänds</div>
<div class="stat"><b id="counter"></b></div>
<div class="stat"><b>Field:</b> <span id="fieldid"></span></div>
<div class="stat"><span id="status" class="badge"></span> · geom-evidens <span id="conf"></span> · <span id="area"></span> ha</div>
<div class="stat"><b>2025:</b> <span id="crop"></span></div>
<div id="sourcebox"></div>

<div>
<button id="prev">← Föregående</button>
<button id="next">Nästa →</button>
<button id="nexttodo">Nästa NYA →</button>
</div>
<button id="overlayToggle" style="width:100%;font-weight:700">Dölj ÅkerAccess-lager</button>

<div class="legend">
<div><span class="swatch" style="background:#ffff00"></span>Åkergräns</div>
<div><span class="swatch" style="background:#00ffff"></span>Bästa kandidatväg</div>
<div><span class="swatch" style="background:#ff00ff"></span>Alternativ kandidatväg</div>
<div><span class="dot" style="background:#ff3300"></span>Bästa infartskandidat</div>
<div><span class="dot" style="background:#ffcc00"></span>Alternativ infartskandidat</div>
</div>

<h3>B2-bedömning</h3>
<div class="small">Plausibel = fysiskt rimlig maskinaccess; vi försöker inte bevisa vilken infart bonden faktiskt använder.</div>
<div id="labels"></div>
<label class="small">Notering</label>
<textarea id="note"></textarea>
<button id="saveNote">Spara notering</button>

<h3>Kandidater</h3>
<div id="candidates"></div>
<h3>Progress</h3>
<div id="progress" class="stat"></div>
<button id="download">Ladda ner B2 QA CSV</button>
<p class="small">Tangentbord: <span class="kbd">←</span>/<span class="kbd">→</span>, <span class="kbd">L</span> lager på/av.</p>
</div><div id="map"></div></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const PAYLOAD={data};
const STORAGE_KEY="akeraccess-b2-sjobo-review";
const saved=JSON.parse(localStorage.getItem(STORAGE_KEY)||"{{}}");
const state={{...saved}};
PAYLOAD.items.forEach(i=>{{
  if(!state[i.field_id] && i.initial_label){{
    state[i.field_id]={{label:i.initial_label,note:i.legacy_note||"",label_source:"legacy_mapped"}};
  }}
}});
localStorage.setItem(STORAGE_KEY,JSON.stringify(state));

let index=Math.max(0,PAYLOAD.items.findIndex(i=>i.needs_review_b2 && !(state[i.field_id]&&state[i.field_id].label)));
let overlaysVisible=true;
const map=L.map("map",{{zoomControl:true}});
const imagery=L.tileLayer(
 "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
 {{maxZoom:20,attribution:"Imagery: Esri / contributors"}}
).addTo(map);
const streets=L.tileLayer(
 "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}",
 {{maxZoom:19,attribution:"Map: Esri / contributors"}}
);
L.control.layers({{"Flygbild":imagery,"Gatukarta":streets}},null,{{collapsed:false}}).addTo(map);
let fieldLayer=null,candidateLayer=null,roadLayer=null,gateLayer=null;

function persist(){{localStorage.setItem(STORAGE_KEY,JSON.stringify(state));}}
function current(){{return PAYLOAD.items[index];}}
function prop(ft,k){{return ft&&ft.properties&&ft.properties[k]!==undefined?ft.properties[k]:"";}}
function esc(s){{return String(s??"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));}}
function relevantRoads(item){{
 const ids=new Set(item.candidates.map(c=>Number(prop(c,"osm_way_id"))));
 return {{type:"FeatureCollection",features:PAYLOAD.roads.features.filter(r=>ids.has(Number(prop(r,"osm_way_id"))))}};
}}
function relevantGates(item){{
 const ids=new Set();
 item.candidates.forEach(c=>String(prop(c,"gate_ids")||"").split(";").forEach(x=>{{if(x)ids.add(Number(x));}}));
 return {{type:"FeatureCollection",features:PAYLOAD.gates.features.filter(g=>ids.has(Number(prop(g,"osm_node_id"))))}};
}}
function vectorLayers(){{return [fieldLayer,roadLayer,candidateLayer,gateLayer].filter(Boolean);}}
function applyOverlay(){{
 vectorLayers().forEach(x=>{{if(overlaysVisible){{if(!map.hasLayer(x))x.addTo(map);}}else if(map.hasLayer(x))map.removeLayer(x);}});
 document.getElementById("overlayToggle").textContent=overlaysVisible?"Dölj ÅkerAccess-lager":"Visa ÅkerAccess-lager";
}}
function renderMap(item){{
 vectorLayers().forEach(x=>{{if(map.hasLayer(x))map.removeLayer(x);}});
 fieldLayer=L.geoJSON(item.field,{{style:{{color:"#ffff00",weight:4,fillOpacity:.08}}}}).addTo(map);
 const bestWay=item.candidates.length?Number(prop(item.candidates[0],"osm_way_id")):NaN;
 roadLayer=L.geoJSON(relevantRoads(item),{{
  style:f=>({{color:Number(prop(f,"osm_way_id"))===bestWay?"#00ffff":"#ff00ff",weight:5,opacity:.9}}),
  onEachFeature:(f,l)=>l.bindPopup("OSM way "+esc(prop(f,"osm_way_id"))+"<br>"+esc(prop(f,"highway"))+" "+esc(prop(f,"surface")))
 }}).addTo(map);
 candidateLayer=L.geoJSON({{type:"FeatureCollection",features:item.candidates}},{{
  pointToLayer:(f,ll)=>L.circleMarker(ll,{{radius:Number(prop(f,"candidate_rank"))===1?9:6,color:Number(prop(f,"candidate_rank"))===1?"#ff3300":"#ffcc00",fillOpacity:.9,weight:3}}),
  onEachFeature:(f,l)=>l.bindPopup("Rank "+esc(prop(f,"candidate_rank"))+" · "+esc(prop(f,"candidate_kind"))+"<br>geom-evidens "+esc(prop(f,"confidence"))+" · "+esc(prop(f,"highway")))
 }}).addTo(map);
 gateLayer=L.geoJSON(relevantGates(item),{{onEachFeature:(f,l)=>l.bindPopup("Gate "+esc(prop(f,"osm_node_id")) )}}).addTo(map);
 map.fitBounds(fieldLayer.getBounds().pad(.45),{{maxZoom:19}});
 applyOverlay();
}}
function renderLabels(item){{
 const box=document.getElementById("labels");box.innerHTML="";
 const rec=state[item.field_id]||{{}};
 PAYLOAD.labels.forEach(l=>{{
  const b=document.createElement("button");b.className="label"+(rec.label===l.value?" active":"");b.textContent=l.text;
  b.onclick=()=>{{state[item.field_id]={{...(state[item.field_id]||{{}}),label:l.value,label_source:"human_b2"}};persist();render();}};
  box.appendChild(b);
 }});
 document.getElementById("note").value=rec.note||"";
}}
function renderCandidates(item){{
 const box=document.getElementById("candidates");box.innerHTML="";
 if(!item.candidates.length){{box.innerHTML='<div class="small">Ingen OSM-kandidat.</div>';return;}}
 item.candidates.forEach(c=>{{
  const p=c.properties||{{}};const d=document.createElement("div");d.className="cand";
  d.innerHTML="<b>#"+esc(p.candidate_rank)+" "+esc(p.candidate_kind)+"</b><br>geom-evidens "+esc(p.confidence)+" · "+esc(p.highway)+" · way "+esc(p.osm_way_id)+
   "<br>surface "+esc(p.surface||"-")+" · tracktype "+esc(p.tracktype||"-")+
   "<br>endpoint "+Number(p.endpoint_distance_m||0).toFixed(1)+" m · inside "+Number(p.inside_length_m||0).toFixed(1)+" m";
  box.appendChild(d);
 }});
}}
function renderSource(item){{
 const box=document.getElementById("sourcebox");
 if(item.sample_source==="LEGACY_REUSED"){{
  box.className="legacy";
  box.innerHTML="<b>Återanvänd v0b</b> · "+esc(item.legacy_label)+(item.mapping_basis?" → <b>"+esc(item.initial_label)+"</b>":"")+
   (item.legacy_note?"<br>Din gamla notering: "+esc(item.legacy_note):"");
 }}else{{
  box.className="topup";box.innerHTML="<b>NYTT B2-fält</b> – behöver bedömas.";
 }}
}}
function progress(){{
 const todo=PAYLOAD.items.filter(i=>i.needs_review_b2);
 const done=todo.filter(i=>state[i.field_id]&&state[i.field_id].label).length;
 document.getElementById("progress").textContent="Nya B2: "+done+" / "+todo.length+" bedömda · total sample "+PAYLOAD.items.length;
}}
function render(){{
 const item=current();
 document.getElementById("counter").textContent="Skifte "+(index+1)+" / "+PAYLOAD.items.length;
 document.getElementById("fieldid").textContent=item.field_id;
 document.getElementById("status").textContent=item.entry_status;
 document.getElementById("conf").textContent=item.best_confidence;
 document.getElementById("area").textContent=Number(item.area_ha).toFixed(2);
 document.getElementById("crop").textContent=item.crop2025_name||"(okänd)";
 renderSource(item);renderLabels(item);renderCandidates(item);progress();renderMap(item);
}}
function move(delta){{index=(index+delta+PAYLOAD.items.length)%PAYLOAD.items.length;render();}}
function nextTodo(){{
 for(let step=1;step<=PAYLOAD.items.length;step++){{
  const j=(index+step)%PAYLOAD.items.length;const i=PAYLOAD.items[j];const r=state[i.field_id]||{{}};
  if(i.needs_review_b2 && !r.label){{index=j;render();return;}}
 }}
 alert("Alla nya B2-fält har en label.");
}}
document.getElementById("prev").onclick=()=>move(-1);
document.getElementById("next").onclick=()=>move(1);
document.getElementById("nexttodo").onclick=nextTodo;
document.getElementById("overlayToggle").onclick=()=>{{overlaysVisible=!overlaysVisible;applyOverlay();}};
document.getElementById("saveNote").onclick=()=>{{
 const i=current();state[i.field_id]={{...(state[i.field_id]||{{}}),note:document.getElementById("note").value,
  label_source:(state[i.field_id]&&state[i.field_id].label_source) || (i.sample_source==="LEGACY_REUSED"?"legacy_mapped":"human_b2")}};
 persist();progress();
}};
document.getElementById("download").onclick=()=>{{
 const header=["review_index_b2","field_id","auto_status","auto_geom_evidence","area_ha","crop2025_name","sample_source","needs_review_b2",
 "legacy_label","legacy_note","initial_label","mapping_basis","final_label","final_note","label_source"];
 const rows=[header];
 PAYLOAD.items.forEach(i=>{{const r=state[i.field_id]||{{}};rows.push([i.review_index_b2,i.field_id,i.entry_status,i.best_confidence,i.area_ha,i.crop2025_name,
 i.sample_source,i.needs_review_b2,i.legacy_label,i.legacy_note,i.initial_label,i.mapping_basis,r.label||"",r.note||"",r.label_source||""]);}});
 const csv=rows.map(r=>r.map(x=>'"'+String(x??"").replaceAll('"','""')+'"').join(",")).join("\\r\\n");
 const blob=new Blob(["\\ufeff"+csv],{{type:"text/csv;charset=utf-8"}});const a=document.createElement("a");
 a.href=URL.createObjectURL(blob);a.download="sjobo_akeraccess_visual_qa_b2.csv";a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}};
document.addEventListener("keydown",e=>{{if(e.target.tagName==="TEXTAREA")return;if(e.key==="ArrowRight")move(1);if(e.key==="ArrowLeft")move(-1);if(e.key==="l"||e.key==="L"){{overlaysVisible=!overlaysVisible;applyOverlay();}}}});
render();
</script></body></html>"""


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--work",default=str(DEFAULT_WORK))
    ap.add_argument("--osm",default=str(DEFAULT_OSM))
    ap.add_argument("--out",default=None)
    args=ap.parse_args()
    work=Path(args.work); osm=Path(args.osm)
    out=Path(args.out) if args.out else work/"review_b2"/"index.html"
    payload=build_payload(work,osm)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(build_html(payload),encoding="utf-8")
    topups=sum(bool(i["needs_review_b2"]) for i in payload["items"])
    print("="*92)
    print("ÅkerAccess STOPPUNKT B2 - REVIEWER")
    print("="*92)
    print(f"Sample fields: {len(payload['items'])}")
    print(f"New fields requiring review: {topups}")
    print(f"Legacy carry-over fields: {len(payload['items'])-topups}")
    print(f"HTML: {out}")
    print("="*92)
    print("STOPPUNKT B2 REVIEWER BUILD: PASS")
    print("="*92)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
