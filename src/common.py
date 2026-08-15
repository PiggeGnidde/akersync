from __future__ import annotations
from pathlib import Path
import hashlib, json, math
import numpy as np

MUN_CODES = {"Lomma":"1262", "Kävlinge":"1261", "Eslöv":"1285"}
CSV_MUN_TO_UI = {"Lomma":"Lomma", "Kavlinge":"Kävlinge", "Eslov":"Eslöv"}

def load_config(path):
    p=Path(path)
    return json.loads(p.read_text(encoding="utf-8"))

def save_json(obj,path):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")

def clean(v,digits=4):
    if v is None: return None
    try:
        if np.isnan(v): return None
    except Exception:
        pass
    return round(float(v),digits)

def sha256_file(path, chunk=8*1024*1024):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def fmt_int_spaces(n):
    return f"{int(n):,}".replace(",", " ")
