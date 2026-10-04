#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-run hosted U5 HTTP smoke without changing remote files."""
from __future__ import annotations
import base64,json,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ENV_PATH=ROOT/".env"

def env():
    out={}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s=raw.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k,v=s.split("=",1);out[k.strip()]=v.strip()
    return out

def b64d(s): return base64.b64decode(s.encode("ascii")).decode("utf-8")

def get(url,user,password):
    token=base64.b64encode(f"{user}:{password}".encode()).decode()
    req=urllib.request.Request(url,headers={"Authorization":"Basic "+token,"Cache-Control":"no-cache","User-Agent":"AkerPass-U5-Verify/1.0"})
    with urllib.request.urlopen(req,timeout=45) as r:return r.status,r.read()

def main():
    e=env();base=e["AKERPASS_PREVIEW_URL"].rstrip("/")+"/";u=e["AKERPASS_PREVIEW_HTTP_USER"];p=b64d(e["AKERPASS_PREVIEW_HTTP_PASSWORD_B64"])
    checks=[]

    st,b=get(base+"?u5verify=1",u,p);t=b.decode("utf-8",errors="replace")
    for token in ("AKERPASS_UNIFIED_WEB_V0A","AKERFRO_ROTATION_V1A_PRIORITY_UI","AKERVATTEN_VISS_UI_V0A"):
        if token not in t: raise RuntimeError("root missing "+token)
    checks.append(("root",st,len(b)))

    st,b=get(base+"data/akerfro/rotation_v1a_priority_override.json?u5verify=1",u,p);d=json.loads(b.decode("utf-8-sig"))
    if (d["rotation_release_fields"],d["bestmatch_v0c_fields"],d["d0_area_lt_1ha_fields"])!=(43,37,6): raise RuntimeError("rotation priority anchors")
    if d["fields"]["61723351559|2B"]["rank"]!=273 or d["fields"]["61723351559|2A"]["rank"]!=1436: raise RuntimeError("Staffanstorp priority anchors")
    checks.append(("rotation_priority",st,43))

    st,b=get(base+"data/akerfro_bestmatch/skane_index.json?u5verify=1",u,p);d=json.loads(b.decode("utf-8-sig"))
    if d["status"]!="FROZEN_BESTMATCH_V0C_PRESENTATION" or d["candidate_fields"]!=16004 or d["field_union_count"]!=5000: raise RuntimeError("BestMatch anchors")
    checks.append(("bestmatch_v0c",st,16004))

    st,b=get(base+"data/akervatten/skane_index.json?u5verify=1",u,p);d=json.loads(b.decode("utf-8-sig"))
    if d["field_count"]!=128636: raise RuntimeError("ÅkerVatten anchor")
    checks.append(("akervatten",st,128636))

    st,b=get(base+"rapskartan25/index.html?u5verify=1",u,p)
    if "AKERPASS_RAPSKARTAN_BACKLINK_V0A" not in b.decode("utf-8",errors="replace"): raise RuntimeError("Rapskartan backlink")
    checks.append(("rapskartan",st,len(b)))

    print("="*100);print("AKERPASS U5 HOSTED VERIFY: PASS");print("="*100)
    for x in checks: print(x)
    print("URL:",base)
    print("Mobile/GPS smoke is still manual on the real phone.")
    print("="*100)
    return 0

if __name__=="__main__":raise SystemExit(main())
