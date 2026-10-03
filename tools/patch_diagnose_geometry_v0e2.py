from pathlib import Path

P = Path(r"C:\AkerMinne_StreetView_STOPA\diagnose_geometry_v0e.py")
if not P.exists():
    raise SystemExit(f"FEL: Hittar inte {P}")

s = P.read_text(encoding="utf-8")

old1 = '''def candidate_files(year:int):
    c=[]
    for root in RAW_ROOTS:
        if not root.exists(): continue
        # First pass: filenames/path explicitly mentioning target year.
        for p in root.rglob("*.gpkg"):
            if str(year) in str(p) and "skifte" in norm(str(p)):
                c.append(p)
        for p in root.rglob("*.parquet"):
            if str(year) in str(p) and "skifte" in norm(str(p)):
                c.append(p)
    return sorted(set(c), key=lambda p:score_candidate(p,year), reverse=True)
'''

new1 = '''def candidate_files(year:int, municipality:str):
    c=[]
    m = norm(municipality)
    for root in RAW_ROOTS:
        if not root.exists(): continue
        for p in root.rglob("*.gpkg"):
            np = norm(str(p))
            if str(year) in str(p) and "skifte" in np and m in np:
                c.append(p)
        for p in root.rglob("*.parquet"):
            np = norm(str(p))
            if str(year) in str(p) and "skifte" in np and m in np:
                c.append(p)
    return sorted(set(c), key=lambda p:score_candidate(p,year) + (100 if m in norm(str(p)) else 0), reverse=True)
'''

if old1 not in s:
    raise SystemExit("FEL: candidate_files-blocket hittades inte. Stoppar utan ändring.")
s = s.replace(old1, new1, 1)

start = s.find('geometry_rows=[]\nsource_rows=[]\nfor year in sorted(target_years):')
end = s.find('\npd.DataFrame(source_rows).to_csv', start)
if start < 0 or end < 0:
    raise SystemExit("FEL: geometri-loopen hittades inte. Stoppar.")

newloop = '''geometry_rows=[]
source_rows=[]
for municipality in sorted(set(truth["municipality"].astype(str))):
    for year in sorted(target_years):
        case_y=truth[(truth["year"]==year) & (truth["municipality"].astype(str)==municipality)]
        if case_y.empty:
            continue
        cur_y=cur[cur["field_id"].isin(set(case_y["field_id"]))].copy()
        if cur_y.empty:
            continue

        cands=candidate_files(year, municipality)
        print(f"\\n{municipality} {year}: historiska geometri-kandidater={len(cands)}")
        hist=None; used=None
        for p in cands[:20]:
            g=read_hist_candidate(p,year,None)
            if g is None or g.empty:
                continue
            if not any("skifte" in norm(c) or "block" in norm(c) for c in g.columns):
                continue
            hist=g.to_crs(3006)
            used=p
            break

        if hist is None:
            source_rows.append({"municipality":municipality,"year":year,"source":"","status":"NOT_FOUND",
                                "candidates":" | ".join(str(x) for x in cands[:10])})
            print(f"  Ingen historisk skiftesgeometri hittades automatiskt för {municipality} {year}.")
            continue

        source_rows.append({"municipality":municipality,"year":year,"source":str(used),"status":"OK","candidates":len(cands)})
        print(f"  använder: {used}")

        attrs=[]
        for c in hist.columns:
            if c=="geometry": continue
            n=norm(c)
            if any(t in n for t in ("block","skifte","gro","crop","kod","areal","area","arslager","year")):
                attrs.append(c)
        attrs=attrs[:16]
        hs=hist.sindex

        for _,case in case_y.iterrows():
            cg=cur_y[cur_y["field_id"]==case["field_id"]]
            if cg.empty: continue
            cg=cg.iloc[0].geometry
            current_area=float(cg.area)

            idx=list(hs.query(cg, predicate="intersects"))
            pieces=[]
            for j in idx:
                hr=hist.iloc[j]
                inter=cg.intersection(hr.geometry)
                a=float(inter.area) if not inter.is_empty else 0.0
                if a<=1.0: continue
                pieces.append((j,hr,a))
            pieces.sort(key=lambda z:z[2], reverse=True)

            plat,plon=case["pano_lat"],case["pano_lon"]
            pano_m=None
            if pd.notna(plat) and pd.notna(plon):
                pano_m=gpd.GeoSeries(gpd.points_from_xy([plon],[plat]),crs=4326).to_crs(3006).iloc[0]

            for rank,(j,hr,a) in enumerate(pieces[:8],1):
                rec={
                    "case_id":case["case_id"],"municipality":case["municipality"],"year":year,
                    "field_id":case["field_id"],"akerMinne_crop":case["crop"],
                    "hist_rank":rank,
                    "overlap_ha":a/10000.0,
                    "share_of_current_pct":100*a/current_area if current_area else math.nan,
                    "hist_polygon_area_ha":float(hr.geometry.area)/10000.0,
                    "share_of_hist_pct":100*a/float(hr.geometry.area) if hr.geometry.area else math.nan,
                    "distance_pano_to_hist_polygon_m":float(pano_m.distance(hr.geometry)) if pano_m is not None else math.nan,
                    "hist_source":str(used),
                }
                for c in attrs:
                    try: rec[c]=hr[c]
                    except Exception: pass
                geometry_rows.append(rec)
'''

s = s[:start] + newloop + s[end:]
P.write_text(s, encoding="utf-8")
print("OK: diagnos v0e2 patchad.")
print("Historisk geometri väljs nu separat för kommun + år.")
