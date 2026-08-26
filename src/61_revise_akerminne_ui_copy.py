#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "dist" / "index.html"
BASE_MARKER = "AKERMINNE_PILOT_UI_V1A"
REVISION_MARKER = "AKERMINNE_PILOT_UI_COPY_R1"

OLD_YEAR_ROW = r'''function akmYearRow(row){const missing=row.s==="NO_PUBLIC_MATCH";const crop=missing?"Ingen offentlig skiftesmatch":akmCropLabel(row.d);const meta=[];if(row.s==="PARTIAL_COVERAGE")meta.push(`${fmt(100*Number(row.c),0)} % av dagens skifte täcks`);const geometry=akmGeometryLabel(row.i);if(geometry)meta.push(geometry);if(row.m)meta.push("överlappande historiska skiften · QA-varning");const components=(row.x||[]).slice(1).map(item=>`<div>+ ${fmt(100*Number(item[1]),1)} % · ${esc(akmCropLabel(item[0]))}</div>`).join("");return`<div class="akm-row"><div class="akm-year">${row.y}</div><div class="akm-main"><div class="akm-mainline"><div class="akm-crop">${esc(crop)}</div>${akmBadge(row.s)}${row.m?'<span class="akm-badge warn">QA</span>':''}</div>${meta.length?`<div class="akm-meta">${esc(meta.join(" · "))}</div>`:""}${components?`<div class="akm-components">${components}</div>`:""}</div></div>`}'''

NEW_YEAR_ROW = r'''function akmYearRow(row){const missing=row.s==="NO_PUBLIC_MATCH",partial=row.s==="PARTIAL_COVERAGE",coverage=Number(row.c||0),lowCoverage=partial&&coverage<=.05;const crop=missing?"Ingen offentlig skiftesmatch":lowCoverage?`Endast ${fmt(100*coverage,0)} % historisk täckning`:akmCropLabel(row.d);const meta=[];if(partial&&!lowCoverage)meta.push(`${fmt(100*coverage,0)} % historisk täckning`);if(lowCoverage)meta.push("Gröduppgift visas inte vid så låg täckning");const geometry=akmGeometryLabel(row.i);if(geometry)meta.push(geometry);if(row.m)meta.push("överlappande historiska skiften · QA-varning");const components=(missing||lowCoverage)?"":(row.x||[]).slice(1).map(item=>`<div>+ ${fmt(100*Number(item[1]),1)} % · ${esc(akmCropLabel(item[0]))}</div>`).join("");return`<div class="akm-row"><div class="akm-year">${row.y}</div><div class="akm-main"><div class="akm-mainline"><div class="akm-crop">${esc(crop)}</div>${akmBadge(row.s)}${row.m?'<span class="akm-badge warn">QA</span>':''}</div>${meta.length?`<div class="akm-meta">${esc(meta.join(" · "))}</div>`:""}${components?`<div class="akm-components">${components}</div>`:""}</div></div>`}'''

COPY_REPLACEMENTS = (
    ('identity==="one_to_one_relaxed"?"gräns ändrad"', 'identity==="one_to_one_relaxed"?"annan gränsdragning"'),
    ('identity==="split"?"historiskt skifte delat"', 'identity==="split"?"dagens skifte var del av ett större skifte"'),
    ('identity==="merge"?"historiska skiften sammanslagna"', 'identity==="merge"?"dagens skifte bestod av flera skiften"'),
    (
        "Historiken beskriver den markyta som utgör dagens 2025-skifte. Små grödkomponenter under 1 % döljs; minst 5 % krävs för statusen flera grödor.",
        "Historiken beskriver markytan som utgör dagens 2025-skifte. Komponenter under 1 % döljs. Ett år markeras som flera grödor när den näst största grödan täcker minst 5 %.",
    ),
    ('${matched}/10 historiska år med match', '${matched}/10 år med historisk täckning'),
    ('gränsändring ${changed} år', 'ändrad skiftesindelning ${changed} år'),
    (
        "Grödnamn följer rätt års kodlista när den finns. Saknad officiell årstabell visas som rå grödkod.",
        "Grödnamn följer Jordbruksverkets officiella årsvisa kodlistor 2015–2025.",
    ),
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1)


def revise_html(html: str) -> str:
    if REVISION_MARKER in html:
        return html
    if BASE_MARKER not in html:
        raise RuntimeError("Base ÅkerMinne UI patch is missing")

    out = _replace_once(html, OLD_YEAR_ROW, NEW_YEAR_ROW, "year-row revision")
    for i, (old, new) in enumerate(COPY_REPLACEMENTS, 1):
        out = _replace_once(out, old, new, f"copy revision {i}")
    out = _replace_once(
        out,
        "/* AKERMINNE_PILOT_UI_V1A */",
        "/* AKERMINNE_PILOT_UI_V1A */\n/* AKERMINNE_PILOT_UI_COPY_R1 */",
        "revision marker",
    )

    required = (
        REVISION_MARKER,
        "historisk täckning",
        "Gröduppgift visas inte vid så låg täckning",
        "dagens skifte bestod av flera skiften",
        "dagens skifte var del av ett större skifte",
        "ändrad skiftesindelning",
        "Jordbruksverkets officiella årsvisa kodlistor 2015–2025",
    )
    missing = [item for item in required if item not in out]
    if missing:
        raise RuntimeError("Revised ÅkerMinne UI missing: " + ", ".join(missing))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    args = ap.parse_args()
    path = Path(args.index)
    if not path.exists():
        raise FileNotFoundError(path)

    original = path.read_text(encoding="utf-8")
    revised = revise_html(original)
    if revised == original:
        print("AKERMINNE UI COPY REVISION: already present")
        return 0

    tmp = path.with_suffix(".copy-r1.tmp.html")
    tmp.write_text(revised, encoding="utf-8")
    check = tmp.read_text(encoding="utf-8")
    if check != revised:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("UI copy revision write verification failed")
    path.unlink(missing_ok=True)
    tmp.replace(path)
    print(f"AKERMINNE UI COPY REVISION: OK · {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
