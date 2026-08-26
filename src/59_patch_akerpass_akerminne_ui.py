#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "dist" / "index.html"
MARKER = "AKERMINNE_PILOT_UI_V1A"

CSS = r'''
/* AKERMINNE_PILOT_UI_V1A */
.akm-summary{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 10px}.akm-chip{font-size:11px;font-weight:750;background:#edf1e9;border-radius:999px;padding:5px 8px;color:#334437}.akm-note{font-size:11px;color:var(--muted);line-height:1.4;margin:0 0 9px}.akm-timeline{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}.akm-row{display:grid;grid-template-columns:48px minmax(0,1fr);gap:8px;padding:8px 9px;border-top:1px solid #edf0eb}.akm-row:first-child{border-top:0}.akm-year{font-weight:850;font-size:13px;padding-top:1px}.akm-main{min-width:0}.akm-mainline{display:flex;align-items:flex-start;gap:6px;justify-content:space-between}.akm-crop{font-weight:750;font-size:12px;line-height:1.3;min-width:0}.akm-badge{flex:none;border-radius:999px;padding:2px 6px;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.03em;background:#edf1e9;color:#38503e}.akm-badge.mixed{background:#fff0cf;color:#765313}.akm-badge.partial{background:#ffe4c4;color:#7a4510}.akm-badge.missing{background:#eceeeb;color:#666}.akm-badge.warn{background:#ffe0dc;color:#8b2f28}.akm-meta{font-size:10px;color:var(--muted);line-height:1.35;margin-top:3px}.akm-components{font-size:10px;color:#445047;line-height:1.35;margin-top:4px}.akm-components div{margin-top:2px}.akm-status-loading{font-size:12px;color:var(--muted);padding:4px 0 9px}
'''

JS = r'''
/* AKERMINNE_PILOT_UI_V1A */
const AKERMINNE_PILOT_FILES={"Skurup":"data/akerminne/1264_skurup.json"};
let currentAkerminne=null,akerminneState="not_pilot",akerminneMunicipality=null;
function akmCropLabel(key){if(!key)return"Grödkod saknas";if(currentAkerminne&&currentAkerminne.crop_names&&currentAkerminne.crop_names[key])return currentAkerminne.crop_names[key];const parts=String(key).split("|");return`Okänd grödkod ${parts[1]||"saknas"} (${parts[0]||"år saknas"})`}
function akmGeometryLabel(identity){return identity==="one_to_one_relaxed"?"gräns ändrad":identity==="split"?"historiskt skifte delat":identity==="merge"?"historiska skiften sammanslagna":identity==="ambiguous"?"komplex gränsändring":""}
function akmBadge(status){return status==="MIXED_CROPS"?'<span class="akm-badge mixed">flera grödor</span>':status==="PARTIAL_COVERAGE"?'<span class="akm-badge partial">delvis</span>':status==="NO_PUBLIC_MATCH"?'<span class="akm-badge missing">saknas</span>':''}
function akmYearRow(row){const missing=row.s==="NO_PUBLIC_MATCH";const crop=missing?"Ingen offentlig skiftesmatch":akmCropLabel(row.d);const meta=[];if(row.s==="PARTIAL_COVERAGE")meta.push(`${fmt(100*Number(row.c),0)} % av dagens skifte täcks`);const geometry=akmGeometryLabel(row.i);if(geometry)meta.push(geometry);if(row.m)meta.push("överlappande historiska skiften · QA-varning");const components=(row.x||[]).slice(1).map(item=>`<div>+ ${fmt(100*Number(item[1]),1)} % · ${esc(akmCropLabel(item[0]))}</div>`).join("");return`<div class="akm-row"><div class="akm-year">${row.y}</div><div class="akm-main"><div class="akm-mainline"><div class="akm-crop">${esc(crop)}</div>${akmBadge(row.s)}${row.m?'<span class="akm-badge warn">QA</span>':''}</div>${meta.length?`<div class="akm-meta">${esc(meta.join(" · "))}</div>`:""}${components?`<div class="akm-components">${components}</div>`:""}</div></div>`}
function akerminneSection(p){if(p.kommun!=="Skurup")return"";if(akerminneState==="loading")return'<details><summary>ÅkerMinne · 2015–2025</summary><div class="akm-status-loading">Laddar historiken…</div></details>';if(akerminneState==="error")return'<details><summary>ÅkerMinne · 2015–2025</summary><div class="akm-status-loading">Historiken kunde inte laddas.</div></details>';if(akerminneState!=="ready"||!currentAkerminne)return'<details><summary>ÅkerMinne · 2015–2025</summary><div class="akm-status-loading">Pilotdata saknas.</div></details>';const history=currentAkerminne.fields&&currentAkerminne.fields[p.id];if(!history)return'<details><summary>ÅkerMinne · 2015–2025</summary><div class="akm-status-loading">Ingen historik hittades för detta skifte.</div></details>';const historical=history.filter(row=>row.y<2025),matched=historical.filter(row=>row.s!=="NO_PUBLIC_MATCH").length,changed=historical.filter(row=>akmGeometryLabel(row.i)).length;return`<details><summary>ÅkerMinne · 2015–2025</summary><div class="section-note">Historiken beskriver den markyta som utgör dagens 2025-skifte. Små grödkomponenter under 1 % döljs; minst 5 % krävs för statusen flera grödor.</div><div class="akm-summary"><span class="akm-chip">${matched}/10 historiska år med match</span>${changed?`<span class="akm-chip">gränsändring ${changed} år</span>`:""}</div><div class="akm-note">Grödnamn följer rätt års kodlista när den finns. Saknad officiell årstabell visas som rå grödkod.</div><div class="akm-timeline">${[...history].reverse().map(akmYearRow).join("")}</div></details>`}
function refreshAkerminneDrawer(name){if(!selectedFieldLayer||!ui.drawer.classList.contains("open"))return;const p=(selectedFieldLayer.feature||{}).properties||{};if(p.kommun===name)ui.drawerBody.innerHTML=fieldPanel(p)}
function loadAkerminnePilot(name,token){currentAkerminne=null;akerminneMunicipality=name;const file=AKERMINNE_PILOT_FILES[name];if(!file){akerminneState="not_pilot";return}akerminneState="loading";fetch(file,{cache:"no-cache"}).then(response=>{if(!response.ok)throw new Error(`ÅkerMinne HTTP ${response.status}`);return response.json()}).then(data=>{if(token!==loadToken||name!==akerminneMunicipality)return;if(data.municipality!==name||data.field_count!==2944)throw new Error("Ogiltig ÅkerMinne pilotpayload");currentAkerminne=data;akerminneState="ready";refreshAkerminneDrawer(name)}).catch(error=>{console.error(error);if(token!==loadToken)return;akerminneState="error";refreshAkerminneDrawer(name)})}
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def patch_html(html: str) -> str:
    if MARKER in html:
        return html
    html = _replace_once(html, "</style>", CSS + "\n</style>", "CSS injection")
    html = _replace_once(html, "function fieldPanel(p){", JS + "\nfunction fieldPanel(p){", "JS injection")
    html = _replace_once(
        html,
        ' <details><summary>Historik / referens</summary>',
        ' ${akerminneSection(p)}\n <details><summary>Historik / referens</summary>',
        "panel injection",
    )
    html = _replace_once(
        html,
        "closeDrawer();selectedFieldLayer=null;try{",
        "closeDrawer();selectedFieldLayer=null;loadAkerminnePilot(name,token);try{",
        "municipality load injection",
    )
    if html.count(MARKER) != 2:
        raise RuntimeError("ÅkerMinne patch marker count mismatch")
    return html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    args = ap.parse_args()
    path = Path(args.index)
    if not path.exists():
        raise FileNotFoundError(path)
    original = path.read_text(encoding="utf-8")
    patched = patch_html(original)
    if patched == original and MARKER in original:
        print("AKERMINNE UI PATCH: already present")
        return 0
    tmp = path.with_suffix(".tmp.html")
    tmp.write_text(patched, encoding="utf-8")
    check = tmp.read_text(encoding="utf-8")
    required = (MARKER, "ÅkerMinne · 2015–2025", "loadAkerminnePilot", "akerminneSection(p)", "data/akerminne/1264_skurup.json")
    missing = [m for m in required if m not in check]
    if missing:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("patched frontend missing: " + ", ".join(missing))
    path.unlink(missing_ok=True)
    tmp.replace(path)
    print(f"AKERMINNE UI PATCH: OK · {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
