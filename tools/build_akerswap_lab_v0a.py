from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path

VERSION="akerswap-virtual-farmers-lab-v0i"
ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/"dist_akerswap_lab_v0a"
WORK=ROOT/"work"/"akerswap_lab_v0a"

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()

def source_candidates():
    explicit=[
        Path(r"C:\AkerSyncRepo\dist_akerpass_unified_v0a"),
        Path(r"C:\AkerSync-AkerPassUnified\dist_akerpass_unified_v0a"),
        Path(r"C:\AkerSync-AkerAccess\dist_akerpass_unified_v0a"),
    ]
    seen=set()
    for p in explicit:
        if p not in seen:
            seen.add(p); yield p
    try:
        for root in sorted(Path("C:/").glob("AkerSync*")):
            p=root/"dist_akerpass_unified_v0a"
            if p not in seen:
                seen.add(p); yield p
    except OSError:
        pass

def valid_source(p):
    try:
        if p.resolve()==TARGET.resolve(): return False
    except OSError:
        return False
    idx=p/"index.html"
    if not idx.is_file(): return False
    t=idx.read_text(encoding="utf-8",errors="replace")
    required=("AKERPASS_UNIFIED_WEB_V0A","AKERNORM_WEB_UI_V1",'data-layer="fro"','data-layer="vatten"')
    return all(x in t for x in required) and "AKERSWAP_VIRTUAL_FARMERS_LAB_V0I" not in t

def find_source():
    hits=[p for p in source_candidates() if valid_source(p)]
    if not hits:
        raise SystemExit("FEL: hittar ingen lokal dist_akerpass_unified_v0a under C:\\AkerSync*.")
    hits.sort(key=lambda p:(p/"index.html").stat().st_mtime,reverse=True)
    return hits[0]

def main():
    src=find_source()
    print("ÅkerPass Unified source:",src)
    if TARGET.exists(): shutil.rmtree(TARGET)
    shutil.copytree(src,TARGET)
    assets=TARGET/"assets";assets.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/"web"/"akerswap_lab_v0a.js",assets/"akerswap_lab_v0a.js")
    shutil.copy2(ROOT/"web"/"akerswap_lab_v0a.css",assets/"akerswap_lab_v0a.css")

    idx=TARGET/"index.html"
    text=idx.read_text(encoding="utf-8")
    if "AKERSWAP_VIRTUAL_FARMERS_SELECT_V0A" in text:
        raise SystemExit("FEL: källan är redan ÅkerSwap-patchad.")
    text=text.replace("</head>",'<link rel="stylesheet" href="assets/akerswap_lab_v0a.css">\n</head>',1)
    text=text.replace("</body>",'<!-- AKERSWAP_VIRTUAL_FARMERS_SELECT_V0A -->\n<script src="assets/akerswap_lab_v0a.js"></script>\n</body>',1)
    idx.write_text(text,encoding="utf-8")

    t=idx.read_text(encoding="utf-8",errors="replace")
    for token in ("AKERSWAP_VIRTUAL_FARMERS_SELECT_V0A","assets/akerswap_lab_v0a.js","assets/akerswap_lab_v0a.css"):
        if token not in t: raise SystemExit("FEL verifiering: "+token+" saknas.")
    if not (assets/"akerswap_lab_v0a.js").is_file() or not (assets/"akerswap_lab_v0a.css").is_file():
        raise SystemExit("FEL: ÅkerSwap-assets saknas.")

    WORK.mkdir(parents=True,exist_ok=True)
    manifest={
        "version":VERSION,"status":"PASS","source_dist":str(src.resolve()),
        "source_index_sha256":sha256(src/"index.html"),"target":str(TARGET.resolve()),
        "target_index_sha256":sha256(idx),"source_mutated":False,"deployment_performed":False
    }
    (WORK/"build_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("="*92)
    print("AKERSWAP_LAB_BUILD_RESULT")
    print("VERDICT=PASS")
    print("MODE=VIRTUAL_FARMERS_CLICK_PLUS_SOLVER")
    print("SOURCE="+str(src))
    print("TARGET="+str(TARGET))
    print("SOURCE_MUTATED=NO")
    print("DEPLOYMENT=NO")
    print("="*92)

if __name__=="__main__": main()
