#!/usr/bin/env python3
from pathlib import Path
import argparse, zipfile
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

 blocks=gpd.read_file(cfg["blocks"]).to_crs(3006)
 skiften=gpd.read_file(cfg["skiften"]).to_crs(3006)
 codes=tuple(MUN_CODES.values())
 b=blocks[blocks.region_kod.astype(str).str.startswith(codes)].copy()
 s=skiften[skiften.blockid.isin(b.blockid)]
 print(f"Block i Skåne-scope: {len(b):,}")
 print(f"Skiften i Skåne-scope: {len(s):,}")
 if len(b)<=5919 or len(s)<=7364:
  raise SystemExit("Skåne-scope ser för litet ut; förväntade fler objekt än v0.92-baslinjen.")

 with zipfile.ZipFile(cfg["soil_zip"]) as z:
  names=z.namelist()
  for req in REQ_SOIL:
   ok=any(n.endswith("/"+req) or n==req for n in names)
   print(f"Jordlager {req}: {'OK' if ok else 'SAKNAS'}")
   if not ok: raise SystemExit(2)

 dem=sorted(list(Path(cfg["dem_dir"]).glob("*.tif"))+list(Path(cfg["dem_dir"]).glob("*.tiff")))
 print(f"DEM GeoTIFF: {len(dem)}")
 if not dem: raise SystemExit("Inga DEM-filer.")

 epsgs=set();tile_widths=[];tile_heights=[];resolutions=[];bounds=[]
 for p in dem:
  with rasterio.open(p) as ds:
   epsgs.add(ds.crs.to_epsg() if ds.crs else None)
   tile_widths.append(round(ds.bounds.right-ds.bounds.left,1))
   tile_heights.append(round(ds.bounds.top-ds.bounds.bottom,1))
   resolutions.append((round(abs(ds.transform.a),3),round(abs(ds.transform.e),3)))
   bounds.append(ds.bounds)
 print("DEM EPSG:",sorted(epsgs,key=lambda x:(x is None,x)))
 print("DEM tile width sample:",sorted(set(tile_widths))[:8])
 print("DEM tile height sample:",sorted(set(tile_heights))[:8])
 print("DEM pixel resolution sample:",sorted(set(resolutions))[:8])
 if not epsgs.issubset({3006,5845}):
  raise SystemExit("Oväntat DEM CRS.")

 # Do not mix the validated legacy 2.5 km files with the current 10 km COGs.
 # rasterio.merge(method='first') would otherwise make overlap precedence depend
 # on filename ordering and silently mix product generations.
 size_classes=set()
 for w,h in zip(tile_widths,tile_heights):
  if 2000<=w<=3000 and 2000<=h<=3000:size_classes.add("legacy_2p5km")
  elif 9000<=w<=11000 and 9000<=h<=11000:size_classes.add("current_10km")
  else:size_classes.add("other")
 if len(size_classes)>1:
  raise SystemExit("DEM-mappen blandar olika rutstorlekar/produktgenerationer: "+str(sorted(size_classes)))
 print("DEM product grid:",next(iter(size_classes)))

 # Bounding-box sanity. Coastal/ocean NoData may be absent, but the downloaded
 # DEM envelope must at least span the agricultural study area.
 dl=min(x.left for x in bounds);db=min(x.bottom for x in bounds)
 dr=max(x.right for x in bounds);dt=max(x.top for x in bounds)
 bl,bb,br,bt=b.total_bounds
 envelope_ok=(dl<=bl and db<=bb and dr>=br and dt>=bt)
 print(f"DEM envelope: {dl:.0f},{db:.0f},{dr:.0f},{dt:.0f}")
 print(f"Skåne farmland bbox: {bl:.0f},{bb:.0f},{br:.0f},{bt:.0f}")
 print("DEM envelope covers farmland bbox:","OK" if envelope_ok else "VARNING")
 if not envelope_ok:
  raise SystemExit("DEM-utsträckningen täcker inte hela Skåne-scope.")

 manifest={
   "blocks":{"path":str(Path(cfg["blocks"]).resolve()),"sha256":sha256_file(cfg["blocks"])},
   "skiften":{"path":str(Path(cfg["skiften"]).resolve()),"sha256":sha256_file(cfg["skiften"])},
   "soil_zip":{"path":str(Path(cfg["soil_zip"]).resolve()),"sha256":sha256_file(cfg["soil_zip"])},
   "dem":{"path":str(Path(cfg["dem_dir"]).resolve()),"count":len(dem),"grid_class":next(iter(size_classes)),"files":[]}
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
