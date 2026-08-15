from __future__ import annotations
from pathlib import Path
import hashlib, json, math
import numpy as np

# Skåne län: all 33 municipalities.  Keep this as the single source of truth
# for municipality selection throughout the pipeline.
MUN_CODES = {
    "Svalöv": "1214",
    "Staffanstorp": "1230",
    "Burlöv": "1231",
    "Vellinge": "1233",
    "Östra Göinge": "1256",
    "Örkelljunga": "1257",
    "Bjuv": "1260",
    "Kävlinge": "1261",
    "Lomma": "1262",
    "Svedala": "1263",
    "Skurup": "1264",
    "Sjöbo": "1265",
    "Hörby": "1266",
    "Höör": "1267",
    "Tomelilla": "1270",
    "Bromölla": "1272",
    "Osby": "1273",
    "Perstorp": "1275",
    "Klippan": "1276",
    "Åstorp": "1277",
    "Båstad": "1278",
    "Malmö": "1280",
    "Lund": "1281",
    "Landskrona": "1282",
    "Helsingborg": "1283",
    "Höganäs": "1284",
    "Eslöv": "1285",
    "Ystad": "1286",
    "Trelleborg": "1287",
    "Kristianstad": "1290",
    "Simrishamn": "1291",
    "Ängelholm": "1292",
    "Hässleholm": "1293",
}

# Explicit region alias makes later CLI/config support (--region skane) trivial
# without duplicating municipality lists in individual processing stages.
REGIONS = {
    "skane": MUN_CODES,
}

# Names that can occur in CSV/intermediate files without Swedish characters.
CSV_MUN_TO_UI = {
    "Svalov": "Svalöv",
    "Staffanstorp": "Staffanstorp",
    "Burlov": "Burlöv",
    "Vellinge": "Vellinge",
    "Ostra Goinge": "Östra Göinge",
    "Orkelljunga": "Örkelljunga",
    "Bjuv": "Bjuv",
    "Kavlinge": "Kävlinge",
    "Lomma": "Lomma",
    "Svedala": "Svedala",
    "Skurup": "Skurup",
    "Sjobo": "Sjöbo",
    "Horby": "Hörby",
    "Hoor": "Höör",
    "Tomelilla": "Tomelilla",
    "Bromolla": "Bromölla",
    "Osby": "Osby",
    "Perstorp": "Perstorp",
    "Klippan": "Klippan",
    "Astorp": "Åstorp",
    "Bastad": "Båstad",
    "Malmo": "Malmö",
    "Lund": "Lund",
    "Landskrona": "Landskrona",
    "Helsingborg": "Helsingborg",
    "Hoganas": "Höganäs",
    "Eslov": "Eslöv",
    "Ystad": "Ystad",
    "Trelleborg": "Trelleborg",
    "Kristianstad": "Kristianstad",
    "Simrishamn": "Simrishamn",
    "Angelholm": "Ängelholm",
    "Hassleholm": "Hässleholm",
}


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
