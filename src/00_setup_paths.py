#!/usr/bin/env python3
from pathlib import Path
import json, os, tkinter as tk
from tkinter import filedialog, messagebox

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"config"/"local_paths.json"

root=tk.Tk(); root.withdraw(); root.attributes("-topmost",True)

def ask_file(title,pattern):
    p=filedialog.askopenfilename(title=title,filetypes=[pattern,("Alla filer","*.*")])
    if not p: raise SystemExit("Avbrutet.")
    return p

def ask_dir(title):
    p=filedialog.askdirectory(title=title)
    if not p: raise SystemExit("Avbrutet.")
    return p

cfg={}
cfg["blocks"]=ask_file("Välj Jordbruksverket arslager_block.gpkg",("GeoPackage","*.gpkg"))
cfg["skiften"]=ask_file("Välj Jordbruksverket arslager_skifte.gpkg",("GeoPackage","*.gpkg"))
cfg["soil_zip"]=ask_file("Välj SLU/DSMS akermarkens-jordarter.zip",("ZIP","*.zip"))
cfg["dem_dir"]=ask_dir("Välj DEM-mappen med Markhöjdmodell .tif")
cfg["whitebox_work_dir"]=str(Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "AkerSyncWork" / "hydrology")
cfg["build_dir"]="data/derived"
cfg["dist_dir"]="dist"

OUT.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
messagebox.showinfo("ÅkerSync",f"Klart.\nSparade sökvägar i:\n{OUT}")
root.destroy()
print("Wrote",OUT)
