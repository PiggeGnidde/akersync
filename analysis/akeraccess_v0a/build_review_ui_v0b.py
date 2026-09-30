#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build ÅkerAccess v0b visual QA reviewer for the frozen Sjöbo STOPPUNKT A sample.

The reviewer is deliberately a human-ground-truth step. It embeds the existing
100-field stratified sample, all OSM entry candidates for those fields, and the
candidate OSM way geometries. Labels are stored in browser localStorage and can
be exported as CSV.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK = ROOT / "work" / "akeraccess_v0a" / "sjobo"
DEFAULT_OSM = ROOT / "data" / "raw" / "akeraccess_osm" / "sjobo_roads_gates.json"

LABELS = [
    ("CORRECT_ENTRY", "RÄTT / plausibel infart"),
    ("WRONG_ENTRY", "FEL kandidat"),
    ("MISSED_ENTRY", "MISSAD infart"),
    ("NO_VISIBLE_ENTRY", "INGEN tydlig infart"),
    ("UNCLEAR", "OKLART"),
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def load_sample(sample_csv: Path) -> list[dict[str, Any]]:
    rows = []
    with sample_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    if len(rows) != 100:
        raise RuntimeError(f"Expected frozen 100-field review sample, got {len(rows)}")
    return rows


def feature_map(geojson: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for feature in geojson.get("features", []):
        fid = str((feature.get("properties") or {}).get("field_id", ""))
        if fid:
            result[fid] = feature
    return result


def build_review_payload(work: Path, osm_path: Path) -> dict[str, Any]:
    sample_csv = work / "sjobo_manual_review_sample.csv"
    sample_geo = work / "sjobo_manual_review_fields.geojson"
    cand_geo = work / "sjobo_entry_candidates.geojson"
    for p in (sample_csv, sample_geo, cand_geo, osm_path):
        if not p.exists():
            raise FileNotFoundError(p)

    sample = load_sample(sample_csv)
    sample_ids = [str(r["field_id"]) for r in sample]
    sample_set = set(sample_ids)

    fields = feature_map(load_json(sample_geo))
    missing_fields = [fid for fid in sample_ids if fid not in fields]
    if missing_fields:
        raise RuntimeError(f"{len(missing_fields)} review fields missing from GeoJSON")

    candidates_all = load_json(cand_geo).get("features", [])
    candidates_by_field: dict[str, list[dict[str, Any]]] = {fid: [] for fid in sample_ids}
    way_ids: set[int] = set()
    gate_ids: set[int] = set()
    for ft in candidates_all:
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
            token = token.strip()
            if token.isdigit():
                gate_ids.add(int(token))

    for fid in sample_ids:
        candidates_by_field[fid].sort(
            key=lambda f: (
                int((f.get("properties") or {}).get("candidate_rank") or 999999),
                -float((f.get("properties") or {}).get("confidence") or 0.0),
            )
        )

    osm = load_json(osm_path)
    nodes: dict[int, tuple[float, float]] = {}
    node_props: dict[int, dict[str, Any]] = {}
    ways: dict[int, dict[str, Any]] = {}
    for el in osm.get("elements", []):
        if el.get("type") == "node" and "id" in el and "lon" in el and "lat" in el:
            nid = int(el["id"])
            nodes[nid] = (float(el["lon"]), float(el["lat"]))
            node_props[nid] = dict(el.get("tags") or {})
        elif el.get("type") == "way" and "id" in el:
            wid = int(el["id"])
            if wid in way_ids:
                ways[wid] = el

    road_features = []
    for wid in sorted(way_ids):
        el = ways.get(wid)
        if not el:
            continue
        coords = [nodes[n] for n in el.get("nodes", []) if int(n) in nodes]
        if len(coords) < 2:
            continue
        road_features.append({
            "type": "Feature",
            "properties": {
                "osm_way_id": wid,
                **{k: v for k, v in (el.get("tags") or {}).items()
                   if k in {"highway", "surface", "tracktype", "smoothness", "width",
                            "maxwidth", "maxheight", "access", "service"}},
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    gate_features = []
    for nid in sorted(gate_ids):
        if nid not in nodes:
            continue
        tags = node_props.get(nid, {})
        gate_features.append({
            "type": "Feature",
            "properties": {
                "osm_node_id": nid,
                **{k: v for k, v in tags.items()
                   if k in {"barrier", "access", "width", "maxwidth"}},
            },
            "geometry": {"type": "Point", "coordinates": list(nodes[nid])},
        })

    items = []
    for i, row in enumerate(sample):
        fid = str(row["field_id"])
        items.append({
            "review_index": i + 1,
            "field_id": fid,
            "entry_status": row.get("entry_status"),
            "best_confidence": row.get("best_confidence"),
            "area_ha": row.get("area_ha"),
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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ÅkerAccess v0b – Sjöbo visual QA</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body{{height:100%;margin:0;font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
#app{{height:100%;display:grid;grid-template-columns:340px 1fr}}
#panel{{padding:14px;overflow:auto;border-right:1px solid #ccc;background:#fff}}
#map{{height:100%}}
h1{{font-size:19px;margin:0 0 8px}}
.small{{font-size:12px;color:#555}}
.stat{{font-size:14px;margin:7px 0}}
.badge{{display:inline-block;padding:3px 7px;border-radius:999px;background:#eee;font-size:12px}}
button{{font-size:14px;padding:9px 10px;margin:4px 2px;cursor:pointer}}
button.label{{display:block;width:100%;text-align:left}}
button.active{{outline:3px solid #111}}
textarea{{width:100%;min-height:70px;box-sizing:border-box}}
#counter{{font-weight:700}}
.cand{{border-top:1px solid #ddd;padding:8px 0;font-size:12px}}
.kbd{{font-family:monospace;background:#eee;padding:1px 4px;border-radius:3px}}
@media(max-width:800px){{#app{{grid-template-columns:1fr;grid-template-rows:43% 57%}}#panel{{border-right:0;border-bottom:1px solid #ccc}}}}
</style>
</head>
<body>
<div id="app">
<div id="panel">
<h1>ÅkerAccess v0b – visual QA</h1>
<div class="small">Frozen STOPPUNKT A sample · Sjöbo · 100 skiften</div>
<div class="stat"><span id="counter"></span></div>
<div class="stat"><b>Field:</b> <span id="fieldid"></span></div>
<div class="stat"><span id="status" class="badge"></span> · conf <span id="conf"></span> · <span id="area"></span> ha</div>

<div>
<button id="prev">← Föregående</button>
<button id="next">Nästa →</button>
</div>

<h3>Din visuella bedömning</h3>
<div id="labels"></div>
<label class="small">Notering</label>
<textarea id="note" placeholder="Ex. tydlig grusinfart över dike; kandidat ligger 20 m fel..."></textarea>
<div>
<button id="saveNote">Spara notering</button>
</div>

<h3>Kandidater</h3>
<div id="candidates"></div>

<h3>Progress</h3>
<div id="progress" class="stat"></div>
<button id="download">Ladda ner QA CSV</button>
<button id="clear">Rensa alla labels</button>
<p class="small">
Labels lagras lokalt i webbläsaren medan du jobbar. Exportera CSV när du är klar.
Tangentbord: <span class="kbd">←</span>/<span class="kbd">→</span> bläddrar.
</p>
</div>
<div id="map"></div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const PAYLOAD={data};
const STORAGE_KEY="akeraccess-v0b-sjobo-review";
const state=JSON.parse(localStorage.getItem(STORAGE_KEY)||"{{}}");
let index=0;
let map=L.map("map",{{zoomControl:true}});
const imagery=L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
  {{maxZoom:20,attribution:"Imagery: Esri / contributors"}}
).addTo(map);
const osm=L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{maxZoom:20,attribution:"© OpenStreetMap contributors"}});
L.control.layers({{"Flygbild":imagery,"OSM":osm}},null,{{collapsed:false}}).addTo(map);

let fieldLayer=null,candidateLayer=null,roadLayer=null,gateLayer=null;

function persist(){{ localStorage.setItem(STORAGE_KEY,JSON.stringify(state)); }}
function current(){{ return PAYLOAD.items[index]; }}
function prop(ft,k){{ return (ft&&ft.properties&&ft.properties[k]!==undefined)?ft.properties[k]:""; }}
function esc(s){{ return String(s??"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c])); }}

function relevantRoads(item){{
  const ids=new Set(item.candidates.map(c=>Number(prop(c,"osm_way_id"))));
  return {{type:"FeatureCollection",features:PAYLOAD.roads.features.filter(r=>ids.has(Number(prop(r,"osm_way_id"))))}};
}}
function relevantGates(item){{
  const ids=new Set();
  item.candidates.forEach(c=>String(prop(c,"gate_ids")||"").split(";").forEach(x=>{{if(x)ids.add(Number(x));}}));
  return {{type:"FeatureCollection",features:PAYLOAD.gates.features.filter(g=>ids.has(Number(prop(g,"osm_node_id"))))}};
}}

function renderMap(item){{
  [fieldLayer,candidateLayer,roadLayer,gateLayer].forEach(x=>{{if(x)map.removeLayer(x);}});
  fieldLayer=L.geoJSON(item.field,{{style:{{color:"#ffff00",weight:4,fillOpacity:0.08}}}}).addTo(map);
  roadLayer=L.geoJSON(relevantRoads(item),{{
    style:f=>({{color:Number(prop(f,"osm_way_id"))===Number(prop(item.candidates[0],"osm_way_id"))?"#00ffff":"#ff00ff",weight:5,opacity:0.9}}),
    onEachFeature:(f,l)=>l.bindPopup("OSM way "+esc(prop(f,"osm_way_id"))+"<br>"+esc(prop(f,"highway"))+" "+esc(prop(f,"surface")))
  }}).addTo(map);
  candidateLayer=L.geoJSON({{type:"FeatureCollection",features:item.candidates}},{{
    pointToLayer:(f,ll)=>L.circleMarker(ll,{{
      radius:Number(prop(f,"candidate_rank"))===1?9:6,
      color:Number(prop(f,"candidate_rank"))===1?"#ff3300":"#ffcc00",
      fillOpacity:0.9,weight:3
    }}),
    onEachFeature:(f,l)=>l.bindPopup(
      "Rank "+esc(prop(f,"candidate_rank"))+" · "+esc(prop(f,"candidate_kind"))+
      "<br>conf "+esc(prop(f,"confidence"))+" · "+esc(prop(f,"highway"))+
      "<br>way "+esc(prop(f,"osm_way_id"))
    )
  }}).addTo(map);
  gateLayer=L.geoJSON(relevantGates(item),{{
    pointToLayer:(f,ll)=>L.marker(ll),
    onEachFeature:(f,l)=>l.bindPopup("Gate "+esc(prop(f,"osm_node_id")))
  }}).addTo(map);
  const bounds=fieldLayer.getBounds();
  map.fitBounds(bounds.pad(0.45),{{maxZoom:19}});
}}

function renderLabels(item){{
  const box=document.getElementById("labels"); box.innerHTML="";
  const rec=state[item.field_id]||{{}};
  PAYLOAD.labels.forEach(l=>{{
    const b=document.createElement("button");
    b.className="label"+(rec.label===l.value?" active":"");
    b.textContent=l.text;
    b.onclick=()=>{{ state[item.field_id]={{...(state[item.field_id]||{{}}),label:l.value}}; persist(); render(); }};
    box.appendChild(b);
  }});
  document.getElementById("note").value=rec.note||"";
}}

function renderCandidates(item){{
  const box=document.getElementById("candidates"); box.innerHTML="";
  if(!item.candidates.length){{box.innerHTML='<div class="small">Ingen OSM-kandidat.</div>';return;}}
  item.candidates.forEach(c=>{{
    const p=c.properties||{{}};
    const d=document.createElement("div"); d.className="cand";
    d.innerHTML="<b>#"+esc(p.candidate_rank)+" "+esc(p.candidate_kind)+"</b>"+
      "<br>conf "+esc(p.confidence)+" · "+esc(p.highway)+" · way "+esc(p.osm_way_id)+
      "<br>surface "+esc(p.surface||"-")+" · tracktype "+esc(p.tracktype||"-")+
      "<br>endpoint "+Number(p.endpoint_distance_m||0).toFixed(1)+" m · inside "+Number(p.inside_length_m||0).toFixed(1)+" m"+
      (p.gate_near?"<br><b>gate near</b>":"");
    box.appendChild(d);
  }});
}}

function renderProgress(){{
  const done=PAYLOAD.items.filter(i=>state[i.field_id]&&state[i.field_id].label).length;
  document.getElementById("progress").textContent=done+" / "+PAYLOAD.items.length+" bedömda";
}}

function render(){{
  const item=current();
  document.getElementById("counter").textContent="Skifte "+(index+1)+" / "+PAYLOAD.items.length;
  document.getElementById("fieldid").textContent=item.field_id;
  document.getElementById("status").textContent=item.entry_status;
  document.getElementById("conf").textContent=item.best_confidence;
  document.getElementById("area").textContent=Number(item.area_ha).toFixed(2);
  renderLabels(item); renderCandidates(item); renderProgress(); renderMap(item);
}}

document.getElementById("prev").onclick=()=>{{index=(index-1+PAYLOAD.items.length)%PAYLOAD.items.length;render();}};
document.getElementById("next").onclick=()=>{{index=(index+1)%PAYLOAD.items.length;render();}};
document.getElementById("saveNote").onclick=()=>{{
  const item=current();
  state[item.field_id]={{...(state[item.field_id]||{{}}),note:document.getElementById("note").value}};
  persist(); renderProgress();
}};
document.getElementById("download").onclick=()=>{{
  const rows=[["review_index","field_id","auto_status","auto_confidence","area_ha","human_label","note"]];
  PAYLOAD.items.forEach(i=>{{
    const r=state[i.field_id]||{{}};
    rows.push([i.review_index,i.field_id,i.entry_status,i.best_confidence,i.area_ha,r.label||"",r.note||""]);
  }});
  const csv=rows.map(r=>r.map(x=>'"'+String(x??"").replaceAll('"','""')+'"').join(",")).join("\\r\\n");
  const blob=new Blob(["\\ufeff"+csv],{{type:"text/csv;charset=utf-8"}});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="sjobo_akeraccess_visual_qa_v0b.csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}};
document.getElementById("clear").onclick=()=>{{
  if(confirm("Rensa ALLA sparade QA-labels?")){{Object.keys(state).forEach(k=>delete state[k]);persist();render();}}
}};
document.addEventListener("keydown",e=>{{
  if(e.target.tagName==="TEXTAREA")return;
  if(e.key==="ArrowRight")document.getElementById("next").click();
  if(e.key==="ArrowLeft")document.getElementById("prev").click();
}});
render();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(DEFAULT_WORK))
    ap.add_argument("--osm", default=str(DEFAULT_OSM))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    work = Path(args.work)
    osm = Path(args.osm)
    out = Path(args.out) if args.out else work / "review_v0b" / "index.html"
    payload = build_review_payload(work, osm)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(payload), encoding="utf-8")

    status_counts = {}
    for item in payload["items"]:
        status_counts[item["entry_status"]] = status_counts.get(item["entry_status"], 0) + 1

    print("=" * 92)
    print("ÅkerAccess v0b - VISUAL QA REVIEWER")
    print("=" * 92)
    print(f"Review fields: {len(payload['items'])}")
    for k, v in sorted(status_counts.items()):
        print(f"  {k:24s} {v:3d}")
    print(f"Candidate road geometries embedded: {len(payload['roads']['features'])}")
    print(f"Gate geometries embedded: {len(payload['gates']['features'])}")
    print(f"HTML: {out}")
    print()
    print("Open the HTML, review fields, then click 'Ladda ner QA CSV'.")
    print("=" * 92)
    print("STOPPUNKT B REVIEWER BUILD: PASS")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
