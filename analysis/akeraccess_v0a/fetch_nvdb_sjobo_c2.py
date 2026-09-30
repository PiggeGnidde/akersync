#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download Sjöbo NVDB C2 data locally using repo-root .env.

Credential stays on the user's machine. This script never prints or stores it.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"src"
if str(SRC) not in sys.path:
    sys.path.insert(0,str(SRC))

from akerpass_secrets import get_secret

API="https://api.trafikinfo.trafikverket.se/v2/data.json"
NS="vägdata.nvdb_dk_o"
SCHEMA="1.2"
BOX="13.45 55.47, 14.05 55.82"
LIMIT=50000
RAW=ROOT/"data"/"raw"/"akeraccess_nvdb_sjobo_c2"

OBJECTS=[
    "Vägbredd",
    "Bärighet",
    "FunktionellVägklass",
    "Höjdhinder_upp_till_45_dm",
    "Väghållare",
    "Vägtrafiknät",
]


def request_xml(key:str,obj:str)->bytes:
    keyq=quoteattr(key)
    objq=quoteattr(obj)
    return (
        "<REQUEST>"
        f"<LOGIN authenticationkey={keyq}/>"
        f"<QUERY objecttype={objq} namespace={quoteattr(NS)} "
        f"schemaversion={quoteattr(SCHEMA)} limit={quoteattr(str(LIMIT))} "
        f"skip={quoteattr(str(skip))} changeid=\"0\">"
        "<FILTER><AND>"
        "<EQ name=\"Deleted\" value=\"false\"/>"
        f"<WITHIN name=\"Geometry.WGS84\" shape=\"box\" value={quoteattr(BOX)}/>"
        "</AND></FILTER>"
        "</QUERY></REQUEST>"
    ).encode("utf-8")


def post(body:bytes,attempts:int=6)->dict:
    last=None
    for i in range(attempts):
        req=urllib.request.Request(
            API,data=body,method="POST",
            headers={
                "Content-Type":"text/xml; charset=utf-8",
                "User-Agent":"AkerSync-AkerAccess-C2/0a",
            },
        )
        try:
            with urllib.request.urlopen(req,timeout=90) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            body=e.read().decode("utf-8",errors="replace")
            raise RuntimeError(f"Trafikverket HTTP {e.code}: {body[:1200]}") from e
        except Exception as e:
            last=e
            if i+1<attempts:
                time.sleep(min(2**i,15))
    raise RuntimeError(f"Trafikverket request failed after {attempts} attempts: {type(last).__name__}: {last}")


def extract(payload:dict,obj:str)->tuple[list[dict],dict]:
    rr=(payload.get("RESPONSE") or {}).get("RESULT") or []
    if not rr:
        raise RuntimeError(f"{obj}: empty RESPONSE.RESULT")
    block=rr[0]
    if block.get("ERROR"):
        err=block["ERROR"]
        raise RuntimeError(f"{obj}: API ERROR {err.get('SOURCE')}: {err.get('MESSAGE')}")
    return list(block.get(obj) or []), dict(block.get("INFO") or {})


def main()->int:
    key=get_secret("TRAFIKVERKET_API_KEY",ROOT)
    RAW.mkdir(parents=True,exist_ok=True)

    print("="*96)
    print("ÅkerAccess C2 - download NVDB Sjöbo")
    print("="*96)
    print("Credential: FOUND locally (.env/environment); value is never printed")
    print(f"WGS84 box: {BOX}")
    print()

    for obj in OBJECTS:
        # SSEQ QUERY does not use a SQL-style skip attribute.
        # For this Sjöbo pilot we expect fewer than LIMIT rows per object.
        payload=post(request_xml(key,obj))
        rows,info=extract(payload,obj)
        print(f"{obj}: {len(rows):,} rows")
        if len(rows) >= LIMIT:
            raise RuntimeError(
                f"{obj}: returned {len(rows):,} rows (= LIMIT). "
                "C2 refuses possible truncation; supported paging/cursor logic is required."
            )
        all_rows=rows

        out={"RESPONSE":{"RESULT":[{obj:all_rows,"INFO":info}]}}
        path=RAW/f"{obj}_v12_sjobo.json"
        path.write_text(json.dumps(out,ensure_ascii=False),encoding="utf-8")
        print(f"  saved {path.relative_to(ROOT)} ({path.stat().st_size/1024/1024:.2f} MiB)")

    print()
    print("NVDB C2 download: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
