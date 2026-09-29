#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VT-A5c: provenance audit of VISS withdrawal motivations before freeze.

Read-only diagnostic. Verifies that every withdrawal motivation stored in
VT-A3 waterbody_evidence.json can be traced to a raw VISS motivation row for
the same EU_CD. Text comparison normalizes whitespace only, because A3/UI may
collapse VISS CR/LF line breaks to spaces without changing semantic content.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parents[1]
A1C=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a1c'
A3=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a3'
OUT=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a5c_provenance'

def load(p):
    if not p.exists(): raise RuntimeError(f'Missing {p}')
    return json.loads(p.read_text(encoding='utf-8-sig'))
def norm(x): return '' if x is None else str(x).strip().upper()
def txt(x): return '' if x is None else str(x).strip()
def norm_ws(x): return ' '.join(txt(x).split())
def is_withdrawal(r):
    t=txt(r.get('MeasureGroundWaterPressureType')).lower()
    return 'vattenuttag' in t

def main():
    raw=load(A1C/'measuregroundwaterpressuremotivations.json')
    evidence=load(A3/'waterbody_evidence.json')
    by_eu=defaultdict(list)
    for r in raw:
        e=norm(r.get('WaterEUID'))
        if e: by_eu[e].append(r)

    print('='*104)
    print('ÅkerKontext · VattenTryck — VT-A5c VISS motivation provenance audit')
    print('='*104)
    print(f'Raw pressure motivation rows: {len(raw):,}')
    print(f'VT-A3 evidence water bodies:  {len(evidence):,}')
    print('Text matching: whitespace-normalized (CR/LF/tabs/repeated spaces only)')

    errors=[]; audited=0
    print('\nPOSITIVE CASE WATER BODIES — WITHDRAWAL MOTIVATIONS')
    print('-'*104)
    for ev in evidence:
        e=norm(ev.get('EU_CD')); name=txt(ev.get('name')) or e
        cats=ev.get('pressure_categories') or []
        ms=ev.get('withdrawal_motivations') or []
        if not cats and not ev.get('quantitative_risk'): continue
        audited+=1
        print(f'\n{e} | {name} | categories={";".join(cats) or "-"} | quantitative_risk={ev.get("quantitative_risk")}')
        raw_w=[r for r in by_eu.get(e,[]) if is_withdrawal(r)]
        print(f'  raw withdrawal rows={len(raw_w)} | A3 stored motivations={len(ms)}')
        for i,r in enumerate(raw_w,1):
            print(f'  RAW[{i}] {txt(r.get("MeasureGroundWaterPressureType"))!r} | class={txt(r.get("Classification"))!r} | date={txt(r.get("Date"))!r}')
            print(f'         {txt(r.get("Motivation"))!r}')
        for i,m in enumerate(ms,1):
            mt=txt(m.get('type')); mm=txt(m.get('motivation')); md=txt(m.get('date'))
            matches=[r for r in raw_w
                     if txt(r.get('MeasureGroundWaterPressureType'))==mt
                     and norm_ws(r.get('Motivation'))==norm_ws(mm)
                     and txt(r.get('Date'))==md]
            ok=bool(matches)
            print(f'  A3 [{i}] provenance={"PASS" if ok else "FAIL"}: {mt!r} | {mm!r}')
            if not ok: errors.append({'EU_CD':e,'name':name,'type':mt,'motivation':mm,'date':md})

    print('\nKÖPINGEBRO / GLEMMINGEBRO RAW-TEXT SEARCH')
    print('-'*104)
    needles=('köpingebro','glemmingebro')
    found=[]
    for r in raw:
        m=txt(r.get('Motivation'))
        if any(n in m.lower() for n in needles):
            found.append(r)
            print(f"EU_CD={norm(r.get('WaterEUID'))} | WaterName={txt(r.get('WaterName'))!r}")
            print(f"type={txt(r.get('MeasureGroundWaterPressureType'))!r} | class={txt(r.get('Classification'))!r} | date={txt(r.get('Date'))!r}")
            print(f"motivation={m!r}")

    text_to_eu=defaultdict(set)
    for r in raw:
        if is_withdrawal(r):
            m=norm_ws(r.get('Motivation'))
            if m and m!='-': text_to_eu[m].add(norm(r.get('WaterEUID')))
    dup={m:sorted(es) for m,es in text_to_eu.items() if len(es)>1}
    print('\nWITHDRAWAL MOTIVATION TEXT REUSED ACROSS MULTIPLE EU_CD')
    print('-'*104)
    if not dup: print('None')
    else:
        for m,es in dup.items(): print(f'{es}: {m!r}')

    OUT.mkdir(parents=True,exist_ok=True)
    report={'raw_rows':len(raw),'evidence_water_bodies':len(evidence),'positive_cases_audited':audited,
            'comparison':'whitespace-normalized motivation; exact EU_CD/type/date',
            'provenance_failures':errors,
            'kopingebro_glemmingebro_hits':[{'EU_CD':norm(r.get('WaterEUID')),'WaterName':txt(r.get('WaterName')),'type':txt(r.get('MeasureGroundWaterPressureType')),'classification':txt(r.get('Classification')),'date':txt(r.get('Date')),'motivation':txt(r.get('Motivation'))} for r in found],
            'duplicate_withdrawal_text_across_eu_cd':dup}
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('\n'+'='*104)
    print(f'Positive case water bodies audited: {audited}')
    print(f'A3→raw provenance failures:         {len(errors)}')
    print(f'Köpingebro/Glemmingebro raw hits:   {len(found)}')
    print(f'Reused withdrawal texts:            {len(dup)}')
    print(f'Saved: {OUT.relative_to(ROOT)}\\audit.json')
    if errors:
        print('VT-A5c PROVENANCE AUDIT: FAIL — do not freeze')
        raise SystemExit(2)
    print('VT-A5c PROVENANCE AUDIT: PASS')
    print('='*104)

if __name__=='__main__': main()
