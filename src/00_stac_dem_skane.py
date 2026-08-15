#!/usr/bin/env python3
"""Discover/download current Lantmäteriet Markhöjdmodell COGs for Skåne.

Credentials are prompted at runtime and are never written to disk.  The script
uses the official STAC height API, discovers the Markhöjdmodell collection,
queries the bbox produced by 00_plan_dem_skane.py and can optionally download
all GeoTIFF/COG assets to a separate dem_skane directory.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import pandas as pd
import rasterio
from pyproj import Transformer

from common import load_config

API="https://api.lantmateriet.se/stac-hojd/v1"


def auth_header(user,password):
    token=base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization":f"Basic {token}"}


def request(url,headers,timeout=60):
    h={"User-Agent":"AkerSync/Skane-MVP"}
    # Never spray Geotorget credentials to an unrelated asset host.  Asset URLs
    # outside lantmateriet.se are normally pre-authorized/signed URLs.
    host=(urlparse(url).hostname or "").lower()
    if host.endswith("lantmateriet.se"):
        h.update(headers)
    return Request(url,headers=h)


def get_json(url,headers):
    try:
        with urlopen(request(url,headers),timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        if e.code in (401,403):
            raise RuntimeError(
                "Ingen behörighet till STAC-höjd (HTTP %s). Beställ först "
                "avgiftsfri behörighet till 'Markhöjdmodell Nedladdning' i "
                "Geotorget och försök igen." % e.code
            ) from e
        raise


def norm(s):
    return (str(s).lower().replace("å","a").replace("ä","a").replace("ö","o"))


def choose_markhojd_collection(collections):
    cand=[]
    for c in collections:
        text=norm(c.get("id",""))+" "+norm(c.get("title",""))+" "+norm(c.get("description",""))
        if "markhojdmodell" in text:
            cand.append(c)
    if not cand:
        names=[f"{c.get('id')} · {c.get('title','')}" for c in collections]
        raise RuntimeError("Hittade ingen Markhöjdmodell-collection. Collections:\n  "+"\n  ".join(names))
    # Prefer the shortest/most generic product id if several historical variants exist.
    cand.sort(key=lambda c:("markhojdmodell" not in norm(c.get("title","")),len(str(c.get("id","")))))
    return cand[0]


def skane_bbox_wgs84(root,cfg):
    plan=root/cfg.get("build_dir","data/derived")/"dem_plan_skane.csv"
    if not plan.exists():
        raise RuntimeError(f"DEM-plan saknas: {plan}. Kör PLAN_SKANE_DEM.bat först.")
    x=pd.read_csv(plan)
    for col in ("lower_left_x","lower_left_y","right_x","top_y"):
        if col not in x.columns:
            raise RuntimeError("DEM-planen är från äldre version. Kör git pull och PLAN_SKANE_DEM.bat igen.")
    left=float(x.lower_left_x.min());bottom=float(x.lower_left_y.min())
    right=float(x.right_x.max());top=float(x.top_y.max())
    tf=Transformer.from_crs(3006,4326,always_xy=True)
    west,south=tf.transform(left,bottom);east,north=tf.transform(right,top)
    return (west,south,east,north),(left,bottom,right,top)


def follow_search(url,headers):
    items=[]
    seen=set()
    while url and url not in seen:
        seen.add(url)
        data=get_json(url,headers)
        items.extend(data.get("features",[]))
        nxt=None
        for link in data.get("links",[]):
            if link.get("rel")=="next" and link.get("href"):
                nxt=link["href"];break
        url=nxt
    return items


def tif_assets(items):
    out=[];seen=set()
    for item in items:
        iid=str(item.get("id",""))
        for key,a in (item.get("assets") or {}).items():
            href=a.get("href")
            if not href:continue
            typ=norm(a.get("type",""));title=norm(a.get("title",""));path=norm(urlparse(href).path)
            is_tif=(path.endswith(".tif") or path.endswith(".tiff") or
                    "tiff" in typ or "geotiff" in typ or "cog" in title)
            if not is_tif:continue
            if href in seen:continue
            seen.add(href)
            size=a.get("file:size")
            if size is None:
                size=(a.get("file") or {}).get("size") if isinstance(a.get("file"),dict) else None
            out.append({"item_id":iid,"asset_key":key,"href":href,"size_bytes":size})
    return out


def human(n):
    try:n=float(n)
    except Exception:return "?"
    units=["B","KB","MB","GB","TB"]
    i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.1f} {units[i]}"


def asset_name(row,index):
    name=Path(unquote(urlparse(row["href"]).path)).name
    if not name or not norm(name).endswith((".tif",".tiff")):
        name=f"{row['item_id']}_{row['asset_key']}_{index:03d}.tif"
    return name


def validate_tif(path):
    with rasterio.open(path) as ds:
        epsg=ds.crs.to_epsg() if ds.crs else None
        if epsg not in (3006,5845):
            raise RuntimeError(f"{path.name}: oväntat CRS {ds.crs}")
        if ds.width<=0 or ds.height<=0:
            raise RuntimeError(f"{path.name}: ogiltig rasterstorlek")
        return epsg,abs(ds.transform.a),abs(ds.transform.e),ds.bounds


def download_asset(row,path,headers):
    tmp=path.with_suffix(path.suffix+".part")
    if tmp.exists():tmp.unlink()
    req=request(row["href"],headers)
    try:
        with urlopen(req,timeout=180) as r,open(tmp,"wb") as f:
            shutil.copyfileobj(r,f,length=8*1024*1024)
    except HTTPError as e:
        # Some asset hosts require the same basic auth even if they are not on
        # api.lantmateriet.se. Retry once with credentials, still never persist them.
        if e.code in (401,403):
            h={"User-Agent":"AkerSync/Skane-MVP",**headers}
            with urlopen(Request(row["href"],headers=h),timeout=180) as r,open(tmp,"wb") as f:
                shutil.copyfileobj(r,f,length=8*1024*1024)
        else:
            raise
    validate_tif(tmp)
    tmp.replace(path)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default="config/local_paths.json")
    ap.add_argument("--download",action="store_true",help="Ladda ned COG-filerna")
    ap.add_argument("--update-config",action="store_true",help="Peka dem_dir på dem_skane efter lyckad nedladdning")
    ap.add_argument("--dest",help="Målmapp; default blir dem_skane bredvid nuvarande DEM-mapp")
    a=ap.parse_args()

    root=Path(__file__).resolve().parents[1]
    cfg_path=root/a.config
    cfg=load_config(cfg_path)
    bbox_wgs,bbox_3006=skane_bbox_wgs84(root,cfg)
    old=Path(cfg["dem_dir"])
    dest=Path(a.dest) if a.dest else old.parent/"dem_skane"

    print("="*72)
    print("ÅkerSync · Lantmäteriet STAC · Skåne DEM")
    print("="*72)
    print("API:",API)
    print("BBox EPSG:3006:",", ".join(f"{v:.0f}" for v in bbox_3006))
    print("BBox WGS84:",",".join(f"{v:.8f}" for v in bbox_wgs))
    print("Målmapp:",dest)
    print()

    user=input("Geotorget användarnamn: ").strip()
    password=getpass.getpass("Geotorget lösenord (visas inte): ")
    headers=auth_header(user,password)

    collections=get_json(API+"/collections",headers).get("collections",[])
    coll=choose_markhojd_collection(collections)
    cid=coll.get("id")
    print(f"Collection: {cid} · {coll.get('title','')}")

    params={
        "collections":cid,
        "bbox":",".join(f"{v:.8f}" for v in bbox_wgs),
        "limit":1000,
    }
    items=follow_search(API+"/search?"+urlencode(params),headers)
    assets=tif_assets(items)
    if not assets:
        raise RuntimeError("STAC-sökningen gav inga GeoTIFF/COG-assets för Skåne-bboxen.")

    known=[int(x["size_bytes"]) for x in assets if x.get("size_bytes") not in (None,"")]
    print(f"STAC items: {len(items)}")
    print(f"GeoTIFF/COG assets: {len(assets)}")
    if known:
        print(f"Rapporterad total storlek: {human(sum(known))} ({len(known)}/{len(assets)} assets med storlek)")
    else:
        print("Rapporterad total storlek: saknas i STAC-metadata")

    manifest=[]
    for i,row in enumerate(assets,1):
        manifest.append({**row,"filename":asset_name(row,i)})
    mdf=pd.DataFrame(manifest)
    outdir=root/cfg.get("build_dir","data/derived");outdir.mkdir(parents=True,exist_ok=True)
    manifest_path=outdir/"dem_stac_skane_manifest.csv"
    mdf.drop(columns=["href"]).to_csv(manifest_path,index=False,encoding="utf-8-sig")
    print("Manifest:",manifest_path)

    if not a.download:
        print("\nPLAN ONLY: inga filer laddades ned.")
        print("När detta ser rimligt ut: kör DOWNLOAD_SKANE_DEM.bat")
        return 0

    dest.mkdir(parents=True,exist_ok=True)
    downloaded=0;skipped=0
    for i,row in enumerate(manifest,1):
        path=dest/row["filename"]
        if path.exists():
            try:
                validate_tif(path);skipped+=1
                print(f"[{i}/{len(manifest)}] finns redan: {path.name}")
                continue
            except Exception:
                print(f"[{i}/{len(manifest)}] ogiltig befintlig fil, laddar om: {path.name}")
                path.unlink()
        print(f"[{i}/{len(manifest)}] laddar {path.name} ({human(row.get('size_bytes'))})")
        download_asset(row,path,headers)
        downloaded+=1

    files=sorted(dest.glob("*.tif"))+sorted(dest.glob("*.tiff"))
    if not files:
        raise RuntimeError("Nedladdningen gav inga DEM-filer.")
    # Quick final validation of every downloaded/current file in the new folder.
    epsgs=set();res=[]
    for p in files:
        e,rx,ry,_=validate_tif(p);epsgs.add(e);res.append((rx,ry))
    print(f"\nDEM klara: {len(files)} filer · nya {downloaded} · återanvända {skipped}")
    print("EPSG:",sorted(epsgs))
    print("Pixelstorlek sample:",res[0] if res else "-")

    if a.update_config:
        cfg["dem_dir"]=str(dest.resolve())
        cfg_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Uppdaterade config dem_dir ->",dest.resolve())

    print("\nSKÅNE DEM: KLART")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,HTTPError,URLError) as e:
        print("\nFEL:",e,file=sys.stderr)
        raise SystemExit(1)
