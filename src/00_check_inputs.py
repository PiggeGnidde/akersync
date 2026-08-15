#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, json, zipfile
import geopandas as gpd
import rasterio
from common import load_config, MUN_CODES, sha256_file, save_json

REQ_SOIL=[
 "dsms2025_ler.tif","dsms2025_sand.tif","dsms2025_silt.tif",
 "dsms2025_organisk_klasser.tif"
]

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--config",default="config/local_paths.json")
 ap.add_argument("--hash-dem",action="store_true")
 a=ap.parse_args()
 root=Path(__file__).resolve().parents[1]
 cfg=load_config(root/a.config if not Path(a.config).is_absolute() else a.config)

 for k in ("blocks","skiften","soil_zip","dem_dir"):
  p=Path(cfg[k])
  if not p.exists(): raise SystemExit(f"SAKNAS: {k}: {p}")

 blocks=gpd.read_file(cfg["blocks"])
 skiften=gpd.read_file(cfg["skiften"])
 blocks=blocks.to_crs(3006); skiften=skiften.to_crs(3006)
 codes=tuple(MUN_CODES.values())
 b=blocks[blocks.region_kod.astype(str).str.startswith(codes)]
 s=skiften[skiften.blockid.isin(b.blockid)]
 print(f"Block i Skåne: {len(b):,} (planeringsreferens 24,619)")
 print(f"Skiften i Skåne: {len(s):,}")

 with zipfile.ZipFile(cfg["soil_zip"]) as z:
  names=z.namelist()
  for req in REQ_SOIL:
   ok=any(n.endswith("/"+req) or n==req for n in names)
   print(f"Jordlager {req}: {'OK' if ok else 'SAKNAS'}")
   if not ok: raise SystemExit(2)

 dem=sorted(Path(cfg["dem_dir"]).glob("*.tif"))
 print(f"DEM .tif: {len(dem):,} (Skåne-MVP har 561 tillgängliga legacy 2.5 km-rutor)")
 if not dem: raise SystemExit("Inga DEM-filer.")
 epsgs=set()
 for p in dem[:min(20,len(dem))]:
  with rasterio.open(p) as ds: epsgs.add(ds.crs.to_epsg() if ds.crs else None)
 print("DEM EPSG sample:",sorted(epsgs,key=lambda x:(x is None,x)))
 if not epsgs.issubset({3006,5845}):
  raise SystemExit("Oväntat DEM CRS.")

 manifest={
   "blocks":{"path":str(Path(cfg["blocks"]).resolve()),"sha256":sha256_file(cfg["blocks"])},
   "skiften":{"path":str(Path(cfg["skiften"]).resolve()),"sha256":sha256_file(cfg["skiften"])},
   "soil_zip":{"path":str(Path(cfg["soil_zip"]).resolve()),"sha256":sha256_file(cfg["soil_zip"])},
   "dem":{"path":str(Path(cfg["dem_dir"]).resolve()),"count":len(dem),"files":[]}
 }
 for p in dem:
  row={"name":p.name,"size":p.stat().st_size}
  if a.hash_dem: row["sha256"]=sha256_file(p)
  manifest["dem"]["files"].append(row)
 out=root/"qa"/"input_manifest.json"
 save_json(manifest,out)
 print("Manifest:",out)
 print("INPUT CHECK: OK")

if __name__=="__main__": main()
