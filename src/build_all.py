#!/usr/bin/env python3
from pathlib import Path
import argparse,json,os,subprocess,sys
from common import load_config

ROOT=Path(__file__).resolve().parents[1]
PY=sys.executable

def run(label,args):
 print("\n"+"="*78);print(label);print("="*78)
 print(" ".join(str(x) for x in args))
 r=subprocess.run([str(x) for x in args],cwd=ROOT)
 if r.returncode!=0:raise SystemExit(f"{label} MISSLYCKADES (kod {r.returncode})")

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--config",default="config/local_paths.json")
 ap.add_argument("--reuse-hydro",action="store_true")
 a=ap.parse_args()
 cfg=load_config(ROOT/a.config)
 d=ROOT/cfg.get("build_dir","data/derived");d.mkdir(parents=True,exist_ok=True)

 run("0. Kontrollera rådata",[PY,"src/00_check_inputs.py","--config",a.config])
 run("1. Geometri",[PY,"src/01_geometry.py","--config",a.config])
 run("2. Jord",[PY,"src/02_soil.py","--config",a.config])
 run("3. Topografi",[PY,"src/03_topography.py",
     "--dem",cfg["dem_dir"],"--blocks",cfg["blocks"],"--out",str(d)])
 hcmd=[PY,"src/04_hydrology.py","--dem",cfg["dem_dir"],"--blocks",cfg["blocks"],
       "--out",str(d),"--work-dir",cfg["whitebox_work_dir"]]
 if a.reuse_hydro:hcmd.append("--reuse")
 run("4. Hydrologi",hcmd)
 twi=Path(cfg["whitebox_work_dir"])/"twi_10m.tif"
 if not twi.exists():raise SystemExit(f"TWI saknas efter hydrologi: {twi}")
 run("5. Åkermarks-TWI",[PY,"src/05_farmland_twi.py","--config",a.config,"--twi",str(twi)])
 run("6. Slutför hydrologifeatures",[PY,"src/06_finalize_hydrology.py","--config",a.config])
 run("7. Bygg v0.92-webb",[PY,"src/07_build_web.py","--config",a.config])
 run("8. QA",[PY,"src/08_verify.py","--config",a.config])
 print("\nKLART: dist/index.html")

if __name__=="__main__":main()
