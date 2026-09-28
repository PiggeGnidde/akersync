"""VT-A5b: inspect all raw VISS evidence for Bjärehalvön.

Read-only diagnostic. Prints every pressure, impact and risk row for
SE625674-131386, with special focus on withdrawal/agriculture motivation.
Also diagnoses why the A4b expandable VISS assessment may be empty.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
A1C=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a1c'
A3=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a3'
TARGET='SE625674-131386'
OUT=ROOT/'data'/'derived'/'akervatten'/'viss_vt_a5b_bjare_motivation'

def load(p):
    if not p.exists(): raise RuntimeError(f'Missing {p}')
    return json.loads(p.read_text(encoding='utf-8-sig'))
def norm(x): return '' if x is None else str(x).strip().upper()
def pretty(x): return json.dumps(x,ensure_ascii=False,indent=2)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    pressures=load(A1C/'measuregroundwaterpressuremotivations.json')
    impacts=load(A1C/'measuregroundwaterimpactmotivations.json')
    risks=load(A1C/'waterriskclassifications.json')
    evidence=load(A3/'waterbody_evidence.json')

    p=[r for r in pressures if norm(r.get('WaterEUID'))==TARGET]
    i=[r for r in impacts if norm(r.get('WaterEUID'))==TARGET]
    rr=[r for r in risks if norm(r.get('EU_CD'))==TARGET]
    ev=[r for r in evidence if norm(r.get('EU_CD'))==TARGET]

    print('='*100)
    print('ÅkerKontext · VattenTryck — VT-A5b Bjärehalvön VISS motivation diagnostic')
    print('='*100)
    print(f'EU_CD: {TARGET}')
    print(f'Raw pressure motivation rows: {len(p)}')
    print(f'Raw impact motivation rows:   {len(i)}')
    print(f'Risk classification rows:     {len(rr)}')
    print(f'VT-A3 evidence rows:          {len(ev)}')

    print('\nALL PRESSURE / MOTIVATION ROWS')
    print('-'*100)
    for n,r in enumerate(p,1):
        print(f'[{n}] type={r.get("MeasureGroundWaterPressureType")!r} | classification={r.get("Classification")!r} | date={r.get("Date")!r}')
        print('    motivation:',repr(r.get('Motivation')))
        refs=r.get('References') or []
        if refs: print('    references:',pretty(refs).replace('\n','\n    '))

    print('\nWITHDRAWAL-RELATED ROWS')
    print('-'*100)
    withdrawal=[]
    for r in p:
        typ=str(r.get('MeasureGroundWaterPressureType') or '')
        if 'uttag' in typ.lower():
            withdrawal.append(r)
            print(f'{typ} | classification={r.get("Classification")!r}')
            print('  motivation:',repr(r.get('Motivation')))
            print('  date:',repr(r.get('Date')))
            print('  references:',pretty(r.get('References') or []))

    print('\nIMPACT MOTIVATIONS')
    print('-'*100)
    for n,r in enumerate(i,1):
        print(f'[{n}] type={r.get("MeasureGroundWaterImpactType")!r} | classification={r.get("Classification")!r}')
        print('    motivation:',repr(r.get('Motivation')))

    print('\nRISK CLASSIFICATION')
    print('-'*100)
    for r in rr:
        for sec in r.get('RiskSections') or []:
            print(f'{sec.get("SectionName")}: {sec.get("Risk")}')
            for imp in sec.get('Impacts') or []:
                print(f'  - {imp.get("Impact")}: {imp.get("Risk")}')

    print('\nVT-A3 WATERBODY EVIDENCE')
    print('-'*100)
    print(pretty(ev[0]) if ev else 'MISSING')

    # Reproduce A4b selection logic to explain an empty details box.
    ui_candidates=[]
    if ev:
        ms=ev[0].get('withdrawal_motivations') or []
        for m in ms:
            typ=str(m.get('type') or '').lower()
            if 'jordbruk' in typ:
                ui_candidates.append(m)
    print('\nA4b DISPLAY DIAGNOSTIC')
    print('-'*100)
    print(f'VT-A3 withdrawal motivations available: {len(ev[0].get("withdrawal_motivations") or []) if ev else 0}')
    print(f'Rows matching UI agriculture filter:    {len(ui_candidates)}')
    nonempty=[m for m in ui_candidates if str(m.get('motivation') or '').strip()]
    print(f'Matching rows with non-empty text:       {len(nonempty)}')
    if ui_candidates:
        for m in ui_candidates: print('  ',repr(m))
    if not nonempty:
        print('DIAGNOSIS: A4b has no motivation text to render for the agriculture row; an empty/open details shell should not be shown.')
    else:
        print('DIAGNOSIS: motivation text exists in A3 and should render; if browser is empty, inspect A4b evidence loading/rendering.')

    result={'EU_CD':TARGET,'pressure_rows':p,'withdrawal_rows':withdrawal,'impact_rows':i,'risk_rows':rr,'a3_evidence':ev,'a4b_matching_rows':ui_candidates,'a4b_nonempty_count':len(nonempty)}
    (OUT/'diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\nSaved:',str((OUT/'diagnostic.json').relative_to(ROOT)).replace('\\','/'))
    print('VT-A5b DIAGNOSTIC COMPLETE — NO DATA OR UI MODIFIED')
    print('='*100)

if __name__=='__main__': main()
