#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose the actual ÅkerFrö municipality-web sidecar schema.

Read-only. Uses the already-built unified access_base if present and otherwise
auto-discovers the existing ÅkerFrö base web. Prints only compact structural
samples and contexts for the Staffanstorp regression fields.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/"work"/"akerpass_unified_web_v0a"/"access_base"/"data"/"akerfro"

ANCHORS=[
    ("61723351559|2A","61723351559","2A"),
    ("61723351559|2B","61723351559","2B"),
    ("61723353349|94A","61723353349","94A"),
]

def typename(x:Any)->str:
    if isinstance(x,dict): return "dict"
    if isinstance(x,list): return "list"
    return type(x).__name__

def short(x:Any,n:int=240)->str:
    try:
        s=json.dumps(x,ensure_ascii=False,separators=(",",":"))
    except Exception:
        s=repr(x)
    return s if len(s)<=n else s[:n]+"…"

def contexts(text:str,needle:str,window:int=180,limit:int=4)->list[str]:
    out=[]; start=0
    low=text.lower(); nd=needle.lower()
    while len(out)<limit:
        i=low.find(nd,start)
        if i<0: break
        a=max(0,i-window); b=min(len(text),i+len(needle)+window)
        out.append(text[a:b].replace("\n"," "))
        start=i+len(needle)
    return out

def walk_shapes(node:Any,path:str="$",depth:int=0,maxdepth:int=5,rows:list|None=None)->None:
    if rows is None: rows=[]
    if depth>maxdepth or len(rows)>120: return
    if isinstance(node,dict):
        keys=list(node.keys())
        rows.append((path,"dict",len(node),keys[:20]))
        for k,v in list(node.items())[:12]:
            if isinstance(v,(dict,list)):
                walk_shapes(v,f"{path}.{k}",depth+1,maxdepth,rows)
    elif isinstance(node,list):
        rows.append((path,"list",len(node),None))
        for i,v in enumerate(node[:3]):
            if isinstance(v,(dict,list)):
                walk_shapes(v,f"{path}[{i}]",depth+1,maxdepth,rows)

def find_matching_nodes(node:Any,needles:list[str],path:str="$",depth:int=0,out:list|None=None)->list:
    if out is None: out=[]
    if depth>12 or len(out)>=20: return out
    if isinstance(node,dict):
        # If any key/value directly contains a target fragment, capture this local object.
        direct=False
        for k,v in node.items():
            if any(n.lower() in str(k).lower() for n in needles):
                direct=True
            if not isinstance(v,(dict,list)) and any(n.lower() in str(v).lower() for n in needles):
                direct=True
        if direct:
            out.append((path,node))
        for k,v in node.items():
            if isinstance(v,(dict,list)):
                find_matching_nodes(v,needles,f"{path}.{k}",depth+1,out)
    elif isinstance(node,list):
        direct=False
        for v in node:
            if not isinstance(v,(dict,list)) and any(n.lower() in str(v).lower() for n in needles):
                direct=True
        if direct:
            out.append((path,node[:30]))
        for i,v in enumerate(node):
            if isinstance(v,(dict,list)):
                find_matching_nodes(v,needles,f"{path}[{i}]",depth+1,out)
    return out

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--akerfro-data",default=str(DEFAULT))
    args=ap.parse_args()
    base=Path(args.akerfro_data)
    if not base.is_dir():
        raise FileNotFoundError(base)

    files=sorted(p for p in base.rglob("*.json") if p.name!="skane_index.json")
    print("="*116)
    print("ÅkerFrö WEB SIDECAR SCHEMA DIAGNOSTIC · READ ONLY")
    print("="*116)
    print("Base:",base)
    print("JSON sidecars:",len(files))

    top_shapes=Counter()
    files_with_anchor=[]
    parsed={}
    for p in files:
        try:
            text=p.read_text(encoding="utf-8-sig")
            obj=json.loads(text)
        except Exception as e:
            print("PARSE FAIL",p.name,type(e).__name__,e)
            continue
        parsed[p]=(text,obj)
        if isinstance(obj,dict):
            top_shapes[tuple(sorted(obj.keys()))]+=1
        else:
            top_shapes[(f"<{typename(obj)}>",)]+=1
        if any(full in text or block in text for full,block,_ in ANCHORS):
            files_with_anchor.append(p)

    print("\nTOP-LEVEL SHAPES")
    for keys,n in top_shapes.most_common(10):
        print(f"  {n:2d} × {list(keys)[:18]}")

    print("\nFILES CONTAINING STAFFANSTORP BLOCK/FIELD IDS")
    if not files_with_anchor:
        print("  NONE")
    else:
        for p in files_with_anchor:
            print(" ",p.relative_to(base))

    # If exact IDs are not present, also locate skifte tokens in plausible Staffanstorp-ish files.
    for full,block,skifte in ANCHORS:
        print("\n"+"-"*116)
        print("ANCHOR",full)
        hits=0
        for p,(text,obj) in parsed.items():
            full_ctx=contexts(text,full)
            block_ctx=contexts(text,block)
            # Skifte alone is noisy; only show if same file also mentions block or if exact full id exists.
            if full_ctx or block_ctx:
                hits+=1
                print("FILE",p.relative_to(base))
                if full_ctx:
                    print("  full-id context:")
                    for x in full_ctx: print("   ",x)
                if block_ctx and not full_ctx:
                    print("  block-id context:")
                    for x in block_ctx: print("   ",x)
                nodes=find_matching_nodes(obj,[full,block,skifte])
                for path,node in nodes[:5]:
                    print("  matching node",path,":",short(node,700))
        if not hits:
            print("  No full/block text occurrence.")

    # Structural profile of one or two representative municipality files.
    print("\n"+"-"*116)
    print("REPRESENTATIVE STRUCTURE")
    reps=files_with_anchor[:2] if files_with_anchor else files[:2]
    for p in reps:
        text,obj=parsed[p]
        print("\nFILE",p.relative_to(base),"bytes",len(text))
        rows=[]
        walk_shapes(obj,rows=rows)
        for path,t,n,keys in rows[:45]:
            if keys is None:
                print(f"  {path}: {t}[{n}]")
            else:
                print(f"  {path}: {t}[{n}] keys={keys}")

    # Global key vocabulary around likely identity/candidate fields.
    key_counts=Counter()
    def collect_keys(node:Any):
        if isinstance(node,dict):
            key_counts.update(map(str,node.keys()))
            for v in node.values():
                if isinstance(v,(dict,list)): collect_keys(v)
        elif isinstance(node,list):
            for v in node[:5000]:
                if isinstance(v,(dict,list)): collect_keys(v)
    for _p,(_text,obj) in list(parsed.items())[:34]:
        collect_keys(obj)

    interesting=[
        k for k,_n in key_counts.most_common()
        if any(tok in k.lower() for tok in (
            "id","block","skift","field","class","rotation","artkandidat","fro","ärt","art"
        ))
    ]
    print("\nLIKELY ID / ÅKERFRÖ KEYS")
    for k in interesting[:100]:
        print(f"  {k}: {key_counts[k]}")

    print("="*116)
    print("DIAGNOSTIC COMPLETE · no files changed")
    print("="*116)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
