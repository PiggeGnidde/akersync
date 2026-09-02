#!/usr/bin/env python3
"""Patch the frozen local ÅkerPass shell with a lazy ÅkerNorm V1 panel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKER = "AKERNORM_WEB_UI_V1"
AKM_MARKER = "AKERMINNE_SKANE_UI_R2"

CSS = r'''
/* AKERNORM_WEB_UI_V1 */
.akn-shell{padding:2px 0 4px}.akn-intro{font-size:11px;color:var(--muted);line-height:1.45;margin:0 0 10px}.akn-list{display:grid;gap:9px}.akn-crop{border:1px solid var(--line);border-radius:12px;background:#fff;overflow:hidden}.akn-crop-main{padding:10px}.akn-title-row{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.akn-crop-name{font-size:13px;font-weight:850;line-height:1.3}.akn-badge{flex:none;border-radius:999px;padding:3px 7px;font-size:9px;font-weight:850;letter-spacing:.025em;text-transform:uppercase;background:#edf1e9;color:#38503e}.akn-badge.official{background:#e7eef7;color:#34526f}.akn-badge.unavailable{background:#eceeeb;color:#626762}.akn-value{font-size:25px;font-weight:900;line-height:1.15;margin-top:7px;color:var(--ink)}.akn-unit{font-size:12px;font-weight:750;margin-left:3px}.akn-label{font-size:11px;font-weight:750;color:#425149;margin-top:2px}.akn-official{font-size:10px;color:var(--muted);line-height:1.4;margin-top:5px}.akn-message{font-size:12px;font-weight:750;line-height:1.4;margin-top:8px}.akn-warnings{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.akn-warning{border-radius:999px;background:#fff0cf;color:#765313;padding:3px 7px;font-size:9px;font-weight:800}.akn-detail{border-top:1px solid #edf0eb;margin:0}.akn-detail>summary{padding:8px 10px;font-size:10px;font-weight:800;color:#4d5a51}.akn-detail-body{padding:0 10px 10px}.akn-detail-grid{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 9px;font-size:10px;line-height:1.35}.akn-detail-grid dt{color:var(--muted)}.akn-detail-grid dd{margin:0;text-align:right;font-weight:700;overflow-wrap:anywhere}.akn-formula{margin-top:8px;padding:7px 8px;border-radius:8px;background:#f3f5f1;font-size:9px;line-height:1.45;overflow-wrap:anywhere}.akn-reasons{font-size:9px;color:var(--muted);line-height:1.45;margin-top:7px}.akn-status{font-size:12px;color:var(--muted);padding:5px 0 10px}.akn-empty{font-size:12px;font-weight:750;padding:4px 0 10px}.akn-retry{border:0;border-radius:8px;padding:6px 8px;background:#e8eee8;color:#334437;font:inherit;font-weight:800;cursor:pointer;margin-top:7px}@media(max-width:700px){.akn-crop-main{padding:9px}.akn-value{font-size:23px}.akn-detail-grid{grid-template-columns:1fr}.akn-detail-grid dd{text-align:left;margin-bottom:3px}}
'''

JS_TEMPLATE = r'''
/* AKERNORM_WEB_UI_V1 */
const AKERNORM_FILES=__AKERNORM_FILES__;
const AKERNORM_V1_CROP_CODES=[2,3,4,20,45,46];
const akernormCache={},akernormLoads={};
function aknAttr(value){return encodeURIComponent(String(value==null?"":value))}
function aknNumber(value,digits=1){return value==null||!Number.isFinite(Number(value))?null:fmt(Number(value),digits)}
function aknReasonLabel(reason){const labels={HISTORY_COMPONENT_ONLY:"Grödan förekommer endast som historisk komponent",HISTORY_LOW_COVERAGE:"Historiken har låg täckning",NO_PUBLISHED_2026_NORM_FOR_CROP_SKO:"Publicerad normskörd saknas för grödan i området",CROP_OUTSIDE_V1_FIELD_MODEL:"Grödan ingår inte i skiftesmodellen",V1_GUARDRAIL_NO_SCORE_ADJUSTMENT:"Ingen skiftesjustering görs för grödan i V1",DOMINANT_SKO_SHARE_BELOW_0_95:"Skiftet har otillräckligt entydigt skördeområde",MISSING_AKERSCORE_SOIL_P50:"ÅkerScore saknas",LOCAL_CROP_SKO_REFERENCE_UNAVAILABLE:"Lokal referenspoäng saknas",INVALID_OR_MISSING_FROZEN_BETA:"Fryst modellparameter saknas",SCORE_OUTSIDE_OBSERVED_REFERENCE_RANGE:"ÅkerScore ligger utanför observerat referensstöd",SCORE_OUTSIDE_P05_P95:"ÅkerScore ligger i referensmaterialets ytterområde"};return labels[reason]||reason}
function aknRow(data,raw){const row={};data.columns.forEach((name,index)=>{const dictionary=(data.dictionaries||{})[name],value=raw[index];row[name]=dictionary?dictionary[value]:value});return row}
function aknAnnualLabels(row,data){return(row.history_years||[]).map(year=>[year,(((data.annual_crop_labels||{})[String(year)]||{})[String(row.crop_code)]||row.crop_name)])}
function aknWarnings(row,data){const warnings=[];if(row.model_status==="FIELD_ADJUSTED_HIGHER_UNCERTAINTY")warnings.push("Högre osäkerhet");if(row.model_status==="FIELD_ADJUSTED_WEAK_EFFECT")warnings.push("Svag skiftesjustering");if(["BELOW_OBSERVED_MIN","ABOVE_OBSERVED_MAX","BELOW_P05_WITHIN_OBSERVED","ABOVE_P95_WITHIN_OBSERVED"].includes(row.score_support_status)&&!warnings.includes("Högre osäkerhet"))warnings.push("Högre osäkerhet");if(new Set(aknAnnualLabels(row,data).map(item=>item[1])).size>1)warnings.push("Årsberoende grödkod");return warnings}
function aknStatusGroup(status){return String(status).startsWith("FIELD_ADJUSTED")?0:String(status).startsWith("OFFICIAL_SKO_ONLY")?1:2}
function aknSortRows(a,b){const ga=aknStatusGroup(a.model_status),gb=aknStatusGroup(b.model_status);if(ga!==gb)return ga-gb;const ap=String(a.model_status).startsWith("UNAVAILABLE")&&!AKERNORM_V1_CROP_CODES.includes(Number(a.crop_code))?1:0,bp=String(b.model_status).startsWith("UNAVAILABLE")&&!AKERNORM_V1_CROP_CODES.includes(Number(b.crop_code))?1:0;if(ap!==bp)return ap-bp;const ay=Math.max(0,...(a.history_years||[])),by=Math.max(0,...(b.history_years||[]));return by-ay||Number(b.history_year_count||0)-Number(a.history_year_count||0)||Number(a.crop_code)-Number(b.crop_code)||String(a.crop_name).localeCompare(String(b.crop_name),"sv")}
function aknDetail(row,data){const years=(row.history_years||[]).join(", ")||"saknas",annualLabels=aknAnnualLabels(row,data),annual=new Set(annualLabels.map(item=>item[1])).size>1?annualLabels.map(item=>`${item[0]}: ${item[1]}`).join(" · "):"",annualRow=annual?`<dt>Årsvisa grödnamn</dt><dd>${esc(annual)}</dd>`:"",norm=aknNumber(row.official_sko_norm_t_ha),score=aknNumber(row.akerscore_value),reference=aknNumber(row.sko_crop_reference_score),beta=aknNumber(row.beta_t_ha_per_score,3),adjustment=aknNumber(row.adjustment_t_ha),reasons=String(row.reason_flags||"").split(";").filter(Boolean).map(aknReasonLabel);let formula="";if(aknStatusGroup(row.model_status)===0&&norm!==null&&score!==null&&reference!==null&&beta!==null)formula=`${norm} + ${beta} × (${score} − ${reference}) = ${aknNumber(row.field_akernorm_t_ha)} t/ha`;return`<details class="akn-detail"><summary>Så beräknas och bedöms värdet</summary><div class="akn-detail-body"><dl class="akn-detail-grid"><dt>Gröda</dt><dd>${esc(row.crop_name)} · kod ${esc(row.crop_code)}</dd><dt>Historik</dt><dd>${row.history_year_count} år · ${esc(years)}</dd>${annualRow}<dt>Officiell normskörd</dt><dd>${norm===null?"saknas":`${norm} t/ha`} · ${data.official_norm_year} · SKO ${esc(row.sko_id)}</dd><dt>ÅkerScore</dt><dd>${score===null?"saknas":score}</dd><dt>Referenspoäng</dt><dd>${reference===null?"ej tillämplig":reference}</dd><dt>Beta</dt><dd>${beta===null?"ej tillämplig":`${beta} t/ha per poäng`}</dd><dt>Justering</dt><dd>${adjustment===null?"ingen":`${adjustment>0?"+":""}${adjustment} t/ha`}</dd><dt>Status</dt><dd>${esc(row.model_status)}</dd><dt>Datakvalitet</dt><dd>${esc(row.history_quality)} · ${esc(row.score_support_status)}</dd><dt>Modellversion</dt><dd>${esc(data.model_version)}</dd></dl>${formula?`<div class="akn-formula">${esc(formula)}</div>`:""}${reasons.length?`<div class="akn-reasons">${reasons.map(esc).join(" · ")}</div>`:""}</div></details>`}
function aknCrop(row,data){const group=aknStatusGroup(row.model_status),official=aknNumber(row.official_sko_norm_t_ha),value=aknNumber(row.display_akernorm_t_ha),warnings=aknWarnings(row,data).map(item=>`<span class="akn-warning">${esc(item)}</span>`).join("");let badge,label,main="",message="";if(group===0&&value!==null){badge="Skiftesanpassad";label="Skiftesanpassad ÅkerNorm";main=`<div class="akn-value">${value}<span class="akn-unit">t/ha</span></div><div class="akn-label">${label}</div><div class="akn-official">Officiell normskörd i SKO ${esc(row.sko_id)}: ${official===null?"saknas":`${official} t/ha`} (${data.official_norm_year})</div>`}else if(group===1&&official!==null){badge="Officiell norm";main=`<div class="akn-value">${official}<span class="akn-unit">t/ha</span></div><div class="akn-label">Officiell normskörd i området</div>`;message='<div class="akn-message">Skiftesanpassad ÅkerNorm: ej tillgänglig ännu</div>'}else{badge="Ej tillgänglig";message=row.model_status==="UNAVAILABLE_NO_OFFICIAL_NORM"&&AKERNORM_V1_CROP_CODES.includes(Number(row.crop_code))?`<div class="akn-message">Officiell normskörd saknas i SKO ${esc(row.sko_id)}. ÅkerNorm ej tillgänglig ännu.</div>`:'<div class="akn-message">ÅkerNorm ej tillgänglig ännu</div>'}return`<article class="akn-crop"><div class="akn-crop-main"><div class="akn-title-row"><div class="akn-crop-name">${esc(row.crop_name)}</div><span class="akn-badge ${group===1?"official":group===2?"unavailable":""}">${badge}</span></div>${main}${message}${warnings?`<div class="akn-warnings">${warnings}</div>`:""}</div>${aknDetail(row,data)}</article>`}
function aknRenderField(data,fieldId){const raw=(data.fields||{})[fieldId];if(!raw||!raw.length)return'<div class="akn-empty">ÅkerNorm ej tillgänglig ännu</div>';const rows=raw.map(item=>aknRow(data,item)).sort(aknSortRows);return`<div class="akn-list">${rows.map(row=>aknCrop(row,data)).join("")}</div>`}
function aknLoadMunicipality(name){if(akernormCache[name])return Promise.resolve(akernormCache[name]);if(akernormLoads[name])return akernormLoads[name];const file=AKERNORM_FILES[name];if(!file)return Promise.reject(new Error("ÅkerNorm-sidecar saknas"));akernormLoads[name]=fetch(file,{cache:"no-cache"}).then(response=>{if(!response.ok)throw new Error(`ÅkerNorm HTTP ${response.status}`);return response.json()}).then(data=>{if(data.schema_version!=="akernorm-web-v1"||data.municipality!==name||!data.fields||Object.keys(data.fields).length!==data.field_count||!Array.isArray(data.columns)||!data.dictionaries)throw new Error("Ogiltig ÅkerNorm-payload");akernormCache[name]=data;return data}).finally(()=>delete akernormLoads[name]);return akernormLoads[name]}
function akernormToggle(element){if(!element.open||element.dataset.loaded==="1")return;const body=element.querySelector(".akn-shell"),name=decodeURIComponent(element.dataset.municipality||""),fieldId=decodeURIComponent(element.dataset.field||"");body.innerHTML='<div class="akn-status">Laddar ÅkerNorm…</div>';aknLoadMunicipality(name).then(data=>{if(!element.isConnected)return;body.innerHTML=`<div class="akn-intro">Normal produktionsnivå – inte prognos för nästa skördeår. Grödor visas från mest till minst tillgängligt underlag.</div>${aknRenderField(data,fieldId)}`;element.dataset.loaded="1"}).catch(error=>{console.error(error);body.innerHTML='<div class="akn-status">ÅkerNorm kunde inte laddas.</div><button class="akn-retry" type="button" onclick="this.closest(\'details\').dataset.loaded=\'\';akernormToggle(this.closest(\'details\'))">Försök igen</button>'})}
function akernormSection(p){if(!AKERNORM_FILES[p.kommun])return"";return`<details class="akn-panel" data-municipality="${aknAttr(p.kommun)}" data-field="${aknAttr(p.id)}" ontoggle="akernormToggle(this)"><summary>ÅkerNorm</summary><div class="akn-shell"><div class="akn-status">Öppna för att ladda skiftesanpassad normal produktionsnivå.</div></div></details>`}
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1)


def patch_html(html: str, mapping: dict[str, str]) -> str:
    if MARKER in html:
        raise RuntimeError("ÅkerNorm patch must be applied to the frozen unpatched base index")
    if AKM_MARKER not in html:
        raise RuntimeError("Frozen all-Skåne ÅkerMinne UI marker is missing")
    if len(mapping) != 33 or "Kristianstad" not in mapping or "Skurup" not in mapping:
        raise RuntimeError("ÅkerNorm UI mapping requires all 33 municipalities")
    mapping_js = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
    js = JS_TEMPLATE.replace("__AKERNORM_FILES__", mapping_js)
    out = _replace_once(html, "</style>", CSS + "\n</style>", "CSS injection")
    out = _replace_once(out, "function fieldPanel(p){", js + "\nfunction fieldPanel(p){", "JS injection")
    panel_anchor = " ${akerminneSection(p)}\n <details><summary>Historik / referens</summary>"
    panel_replacement = " ${akerminneSection(p)}\n ${akernormSection(p)}\n <details><summary>Historik / referens</summary>"
    out = _replace_once(out, panel_anchor, panel_replacement, "field panel injection")
    required = (
        MARKER, "ÅkerNorm", "Normal produktionsnivå – inte prognos för nästa skördeår",
        "Skiftesanpassad ÅkerNorm", "Officiell normskörd i området",
        "ÅkerNorm ej tillgänglig ännu", "Officiell normskörd saknas i SKO",
        "Årsberoende grödkod", "Årsvisa grödnamn", "Högre osäkerhet", "Svag skiftesjustering",
        "akernormToggle(this)", '"Kristianstad":"data/akernorm/', "${akerminneSection(p)}",
    )
    missing = [item for item in required if item not in out]
    if missing:
        raise RuntimeError("Patched ÅkerNorm UI missing: " + ", ".join(missing))
    forbidden = (
        "förväntad skörd nästa år", "uppmätt skörd", "faktisk skörd", "garanterad skörd",
        "satellitverifierad", "individuellt 95 %", "avvikelse från faktisk skörd",
    )
    present = [item for item in forbidden if item.casefold() in out.casefold()]
    if present:
        raise RuntimeError("Forbidden ÅkerNorm web copy present: " + ", ".join(present))
    if out.count(MARKER) != 2:
        raise RuntimeError("ÅkerNorm UI marker count mismatch")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--web-index", required=True, type=Path)
    args = parser.parse_args()
    index = json.loads(args.web_index.read_text(encoding="utf-8-sig"))
    entries = index.get("municipalities") or []
    mapping = {str(row["municipality"]): str(row["file"]) for row in entries}
    html = args.index.read_text(encoding="utf-8")
    patched = patch_html(html, mapping)
    temporary = args.index.with_suffix(".akernorm.tmp.html")
    temporary.write_text(patched, encoding="utf-8")
    if temporary.read_text(encoding="utf-8") != patched:
        raise RuntimeError("ÅkerNorm patched index write verification failed")
    temporary.replace(args.index)
    print(f"AKERNORM V1 UI PATCH: PASS · {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
