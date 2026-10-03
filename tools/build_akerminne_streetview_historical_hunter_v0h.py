from pathlib import Path
import shutil

ROOT = Path(r"C:\AkerMinne_StreetView_STOPA")
SRC = ROOT / "src" / "akerminne_streetview_positive_hunt_v0g.py"
DST = ROOT / "src" / "akerminne_streetview_historical_hunter_v0h.py"
BAT = ROOT / "RUN_V0H.bat"

if not SRC.exists():
    raise SystemExit(f"FEL: Hittar inte {SRC}. Kör build_v0g.py först.")

s = SRC.read_text(encoding="utf-8")
if '"version": "v0g"' not in s:
    raise SystemExit("FEL: v0h-byggaren förväntar v0g som bas.")

s = s.replace(
    'DEFAULT_OUT = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_positive_hunt_v0g")',
    'DEFAULT_OUT = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_historical_hunter_v0h")', 1)

# v0g inherited the original two-municipality loader. v0h must really load all Skåne.
OLD_READ_MINNE = r'''def read_minne(root: Path) -> pd.DataFrame:
    frames = []
    for m in MUNICIPALITIES:
        files = locate_minne_files(root, m)
        if not files:
            raise FileNotFoundError(f"Hittar ingen ÅkerMinne parquet för {m} under {root}")
        for p in files:
            d = pd.read_parquet(p)
            d = d.copy()
            d["__municipality"] = m
            d["__source"] = str(p)
            frames.append(d)
    df = pd.concat(frames, ignore_index=True, sort=False)
    return normalize_minne_long(df)
'''

NEW_READ_MINNE = r'''def read_minne(root: Path) -> pd.DataFrame:
    municipalities = [
        "bjuv","bromolla","burlov","bastad","eslov","helsingborg","hassleholm",
        "hoganas","horby","hoor","klippan","kristianstad","kavlinge","landskrona",
        "lomma","lund","malmo","osby","perstorp","simrishamn","sjobo","skurup",
        "staffanstorp","svalov","svedala","tomelilla","trelleborg","vellinge",
        "ystad","astorp","angelholm","orkelljunga","ostra_goinge"
    ]
    frames = []
    missing = []
    for m in municipalities:
        files = locate_minne_files(root, m)
        if not files:
            missing.append(m)
            continue
        for p in files:
            d = pd.read_parquet(p)
            d = d.copy()
            d["__municipality"] = m
            d["__source"] = str(p)
            frames.append(d)
    if not frames:
        raise FileNotFoundError(f"Hittar inga ÅkerMinne-kommunfiler under {root}")
    if missing:
        print("VARNING: ÅkerMinne kommunfiler saknas för:", missing)
    df = pd.concat(frames, ignore_index=True, sort=False)
    out = normalize_minne_long(df)
    print(f"ÅkerMinne kommuner inlästa: {out['municipality'].nunique()} ({sorted(out['municipality'].unique())})")
    return out
'''

if OLD_READ_MINNE not in s:
    raise SystemExit("FEL: read_minne-blocket hittades inte i v0g-basen.")
s = s.replace(OLD_READ_MINNE, NEW_READ_MINNE, 1)

OLD_POOL_PRINT = r'''    for m in MUNICIPALITIES:
        pm = pool[pool["municipality"] == m]
        print(f"  {m.title()}: {len(pm):,}; höstraps={int(pm['truth_positive'].sum()):,}; negativa ej raps/rybs={int((~pm['rape_any']).sum()):,}")
'''

NEW_POOL_PRINT = r'''    print(f"Kommuner i kandidatpool: {pool['municipality'].nunique()}")
    rape_by_m = pool[pool["truth_positive"]].groupby("municipality").size().sort_values(ascending=False)
    print("Höstraps field-years, topp 10 kommuner:", rape_by_m.head(10).to_dict())
'''

if OLD_POOL_PRINT not in s:
    raise SystemExit("FEL: pool-printblocket hittades inte i v0g-basen.")
s = s.replace(OLD_POOL_PRINT, NEW_POOL_PRINT, 1)

HELPERS = r'''

# ---------------- v0h HISTORICAL MAY HUNTER ----------------
V0H_YEARS = (2022, 2024)
V0H_TARGET_N = 30
V0H_MAX_PER_MUNICIPALITY = 4


def discover_historical_candidates_v0h(pool, meta: StreetViewMetadata, max_fields: int = 15000):
    q = pool[(pool["truth_positive"]) & (pool["year"].astype(int).isin(V0H_YEARS))].copy()
    if q.empty:
        return gpd.GeoDataFrame(columns=list(pool.columns), geometry="geometry", crs=pool.crs)

    # One row per field-year; rank by road/access proxy first.
    q = q.sort_values(["base_score", "year", "field_id"], ascending=[False, False, True])
    q = q.drop_duplicates(["field_id", "year"]).head(max_fields).copy()
    q = gpd.GeoDataFrame(q, geometry="geometry", crs=pool.crs).to_crs(4326)

    records = []
    checked = strict = pano_ok = 0

    for i, (_, f) in enumerate(q.iterrows(), 1):
        checked += 1
        municipality = str(f["municipality"])
        year = int(f["year"])

        hm = _strict_hist_match_v0f(f.geometry, municipality, year)
        if hm is None:
            if i % 100 == 0:
                print(f"  checked {i}/{len(q)}; strict={strict}, pano={pano_ok}, candidates={len(records)}")
            continue
        strict += 1

        # We only need a nearby current panorama. Historical dates are inspected manually via See more dates.
        hit = query_best_capture_metadata(meta, hm["geometry"], n_points=6)
        if (hit.status != "OK" or hit.pano_id is None or
                hit.dist_query_to_pano_m is None or hit.dist_query_to_pano_m > 30.0):
            if i % 100 == 0:
                print(f"  checked {i}/{len(q)}; strict={strict}, pano={pano_ok}, candidates={len(records)}")
            continue
        pano_ok += 1

        c = hm["geometry"].representative_point()
        heading = _bearing_v0f(float(hit.lat), float(hit.lon), float(c.y), float(c.x))

        rec = dict(f)
        rec.update(
            geometry=hm["geometry"],
            year=year,
            crop=f["crop"],
            truth_positive=True,
            rape_any=True,
            meta_status=hit.status,
            meta_date=hit.date,
            pano_id=hit.pano_id,
            pano_lat=hit.lat,
            pano_lon=hit.lon,
            query_lat=hit.query_lat,
            query_lon=hit.query_lon,
            pano_boundary_dist_m=float(hit.dist_query_to_pano_m),
            heading_deg=heading,
            hist_share_current_pct=hm["hist_share_current_pct"],
            hist_share_hist_pct=hm["hist_share_hist_pct"],
            hist_second_share_current_pct=hm["hist_second_share_current_pct"],
            hist_grdkod_mar=hm["hist_grdkod_mar"],
            hist_skiftesbeteckning=hm["hist_skiftesbeteckning"],
            hist_source=hm["hist_source"],
        )

        # Historical date is unknown to the API. Rank on what we do know:
        # road/pano closeness + access score + mild preference for 2022 (empirically seen to have May coverage).
        year_bonus = 20.0 if year == 2022 else 10.0
        rec["meta_score"] = 500.0 - 5.0 * rec["pano_boundary_dist_m"] + year_bonus
        rec["total_score"] = float(f["base_score"]) + rec["meta_score"]
        records.append(rec)

        if len(records) <= 20 or len(records) % 25 == 0:
            print(f"  CAND {len(records):03d}: {municipality} {year}  "
                  f"pano_dist={rec['pano_boundary_dist_m']:.1f} m  current_pano={rec['meta_date']}")

        # Build a healthy buffer, then rank/diversify.
        if len(records) >= 150:
            print(f"  150 bra historiska kandidater hittade efter {i} field-years; stoppar och rankar.")
            break

        if i % 100 == 0:
            print(f"  checked {i}/{len(q)}; strict={strict}, pano={pano_ok}, candidates={len(records)}")

    if not records:
        return gpd.GeoDataFrame(columns=list(q.columns), geometry="geometry", crs=4326)

    d = gpd.GeoDataFrame(records, geometry="geometry", crs=4326)
    d = d.sort_values(["pano_boundary_dist_m", "total_score"], ascending=[True, False])

    # Geographic diversity: max four per municipality on the first pass.
    picked = []
    counts = {}
    for idx, r in d.iterrows():
        m = str(r["municipality"])
        if counts.get(m, 0) >= V0H_MAX_PER_MUNICIPALITY:
            continue
        picked.append(idx)
        counts[m] = counts.get(m, 0) + 1
        if len(picked) >= V0H_TARGET_N:
            break

    if len(picked) < V0H_TARGET_N:
        for idx in d.index:
            if idx in picked:
                continue
            picked.append(idx)
            if len(picked) >= V0H_TARGET_N:
                break

    return d.loc[picked].copy()
'''

needle = 'def candidate_pool(minne: pd.DataFrame, access_gdf):\n'
if needle not in s:
    raise SystemExit("FEL: candidate_pool hittades inte.")
s = s.replace(needle, HELPERS + '\n' + needle, 1)

# Replace v0g run selection section.
start = s.find('    if not api_key:\n        raise RuntimeError("v0g Skåne Positive Hunt kräver Google metadata-API.")')
end = s.find('    meta.save()', start)
if start < 0 or end < 0:
    raise SystemExit("FEL: v0g selection block hittades inte.")

newblock = '''    if not api_key:\n        raise RuntimeError("v0h Historical May Hunter kräver Google metadata-API för att hitta närliggande panorama.")\n    cache_path = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_stopa\\metadata_cache.json")\n    meta = StreetViewMetadata(api_key, cache_path)\n    print("Urvalsregel v0h: ÅkerMinne=Raps (höst), år 2022/2024, historisk symmetrisk 1:1 >=95%, aktuellt pano <=30 m. Historiskt majdatum kontrolleras manuellt med See more dates.")\n    hist = discover_historical_candidates_v0h(pool, meta, max_fields=15000)\n    if hist is None or len(hist) == 0:\n        raise RuntimeError("Inga historiska rapskandidater hittades.")\n    selected_parts = [hist]\n    print(f"\\nHISTORICAL MAY HUNTER: {len(hist)} kandidater till manuell See more dates-kontroll.")\n    print("  per kommun:", hist["municipality"].value_counts().to_dict())\n    print("  målår:", hist["year"].value_counts().sort_index().to_dict())\n    print("  panoavstånd m:", [round(float(x),1) for x in hist["pano_boundary_dist_m"]])\n'''
s = s[:start] + newblock + s[end:]

# IDs and local storage.
s = s.replace('d["case_id"] = [f"GOLD{i:02d}" for i in range(1, len(d) + 1)]',
              'd["case_id"] = [f"HIST{i:02d}" for i in range(1, len(d) + 1)]', 1)
s = s.replace("const STORE='akerminne_streetview_positive_hunt_v0g_answers';",
              "const STORE='akerminne_streetview_historical_hunter_v0h_answers';", 1)

# UI title/instructions.
s = s.replace('STOPPUNKT G — SKÅNE POSITIVE HUNT: 10 guldgula höstrapsfält',
              'STOPPUNKT H — HISTORICAL MAY HUNTER: hitta 10 guldgula höstrapsfält', 1)

s = s.replace(
    'Alla fall är <b>ÅkerMinne=Raps (höst)</b> men detta hålls dolt tills du scorear. Street View är från <b>maj exakt samma år</b>, historisk geometri är strikt 1:1 och panorama ligger nära fältet. <b>RAPS = sammanhängande gul blomning över odlad yta. Spridda gula maskrosor i gräs/vall = INTE RAPS.</b>',
    'Alla kandidater är valda från ÅkerMinne=Raps (höst) med strikt historisk 1:1-geometri. <b>Öppna Street View → See more dates / Se fler datum → välj målåret.</b> Finns en <b>majbild</b>, bedöm den. <b>RAPS = sammanhängande gul blomning över odlad yta. Spridda gula maskrosor i gräs/vall = INTE RAPS.</b> Om maj målåret saknas: välj INGEN BILD.', 1)

s = s.replace(
    'Urvalet är ett riktat positivt QA-test: endast ÅkerMinne=Raps (höst). Målet är 10 visuellt starka majfall, inte ett prevalensestimat.',
    'Urvalet är ett riktat positivt QA-test. Målet är att manuellt hitta 10 tydliga historiska majbilder; kandidater utan majbild målåret räknas inte som fel.', 1)

# Rename INGEN BILD -> INGEN MAJ throughout visible UI only.
s = s.replace('INGEN BILD', 'INGEN MAJ')

s = s.replace('"version": "v0g"', '"version": "v0h"', 1)
s = s.replace(
    '"method": "SKANE POSITIVE HUNT: AkerMinne winter-rape positives only; exact-May Street View pano in same year; exact pano ID; historical field polygon; symmetric 1:1 overlap >=95%; panorama <=25 m; blind review; no imagery downloaded.",',
    '"method": "HISTORICAL MAY HUNTER: AkerMinne winter-rape positives in 2022/2024; historical field polygon; symmetric 1:1 overlap >=95%; current nearby panorama <=30 m; human selects historical May image using See more dates; no imagery downloaded.",', 1)

DST.write_text(s, encoding="utf-8")

BAT_TEXT = r'''@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  AkerMinne x Street View - STOPPUNKT H v0h
echo  HISTORICAL MAY HUNTER - find 10 gold-yellow rape fields
echo ============================================================

python --version >nul 2>&1
if errorlevel 1 (
  echo FEL: Python hittas inte i PATH.
  pause
  exit /b 1
)

python -c "import pandas,requests,geopandas,shapely,pyarrow,dotenv" >nul 2>&1
if errorlevel 1 (
  echo Installerar saknade Python-paket...
  python -m pip install -r requirements_stopa.txt
  if errorlevel 1 goto :fail
)

if not exist .env (
  echo FEL: .env saknas. Kor RUN_STOPA.bat en gang och lagg in Google-nyckeln.
  goto :fail
)

python src\akerminne_streetview_historical_hunter_v0h.py
if errorlevel 1 goto :fail

start "" "C:\AkerSync-AkerAccess\work\akerminne_streetview_historical_hunter_v0h\review.html"
echo.
echo KLART. Kontrollera See more dates och leta efter maj under malaret.
pause
exit /b 0

:fail
echo.
echo KORNINGEN MISSLYCKADES. Kopiera CMD-outputen till ChatGPT.
pause
exit /b 1
'''
BAT.write_text(BAT_TEXT, encoding="utf-8", newline="\r\n")

print("OK: v0h Historical May Hunter skapad. v0f/v0g är orörda.")
print(f"  Script: {DST}")
print(f"  Kör:    {BAT}")
print(r"  Output: C:\AkerSync-AkerAccess\work\akerminne_streetview_historical_hunter_v0h")
