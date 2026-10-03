from pathlib import Path
import shutil

ROOT = Path(r"C:\AkerMinne_StreetView_STOPA")
SRC = ROOT / "src" / "akerminne_streetview_stopa.py"
DST = ROOT / "src" / "akerminne_streetview_positive_hunt_v0g.py"
BAT = ROOT / "RUN_V0G.bat"

if not SRC.exists():
    raise SystemExit(f"FEL: Hittar inte {SRC}")

s = SRC.read_text(encoding="utf-8")
if '"version": "v0f"' not in s:
    raise SystemExit("FEL: v0g-byggaren förväntar v0f som bas. Stoppar utan ändring.")

# Keep v0f untouched; create a dedicated v0g script.
s = s.replace(
    'DEFAULT_OUT = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_may_gold_v0f")',
    'DEFAULT_OUT = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_positive_hunt_v0g")', 1)

# Positive hunt can tolerate a little more distance because flowering rape is visually obvious.
s = s.replace('MAX_PANO_BOUNDARY_M = 15.0', 'MAX_PANO_BOUNDARY_M = 25.0', 1)

HELPERS = r'''

# ---------------- v0g SKANE POSITIVE HUNT ----------------

def _rape_years_by_field_v0g(pool):
    p = pool[pool["truth_positive"]].copy()
    years = {}
    meta = {}
    for r in p.itertuples(index=False):
        fid = str(r.field_id)
        years.setdefault(fid, set()).add(int(r.year))
        # Keep one representative row with municipality/base score/geometry.
        if fid not in meta:
            meta[fid] = r
    return years, meta


def discover_positive_gold_v0g(pool, meta: StreetViewMetadata, max_fields: int = 20000):
    rape_years, rep = _rape_years_by_field_v0g(pool)
    fields = pool[pool["field_id"].isin(rape_years.keys())].copy()
    fields = fields.sort_values(["base_score", "field_id"], ascending=[False, True])
    fields = fields.drop_duplicates("field_id").head(max_fields).copy()
    fields = gpd.GeoDataFrame(fields, geometry="geometry", crs=pool.crs).to_crs(4326)

    records = []
    checked = 0
    exact_may = 0
    strict = 0

    print(f"Skåne: unika fält med minst ett ÅkerMinne-år Raps (höst): {len(fields):,}")

    for i, (_, f) in enumerate(fields.iterrows(), 1):
        checked += 1

        # Cheap first pass on current geometry.
        first = query_best_capture_metadata(meta, f.geometry, n_points=4)
        y, mo = date_parts(first.date)

        if (first.status != "OK" or y not in rape_years.get(str(f["field_id"]), set()) or mo != 5 or
                first.dist_query_to_pano_m is None or first.dist_query_to_pano_m > MAX_PANO_BOUNDARY_M):
            if i % 100 == 0:
                print(f"  checked {i}/{len(fields)}; exact-maj+rapsår={exact_may}, strict-gold={len(records)}")
            continue

        exact_may += 1

        municipality = str(f["municipality"])
        hm = _strict_hist_match_v0f(f.geometry, municipality, int(y))
        if hm is None:
            continue
        strict += 1

        # Re-query using the actual historical field polygon for that year.
        exact = query_best_capture_metadata(meta, hm["geometry"], n_points=8)
        y2, mo2 = date_parts(exact.date)
        if (exact.status != "OK" or y2 != int(y) or mo2 != 5 or
                exact.dist_query_to_pano_m is None or exact.dist_query_to_pano_m > MAX_PANO_BOUNDARY_M):
            continue

        # Recover exact ÅkerMinne row for this field/year.
        hq = pool[(pool["field_id"].astype(str) == str(f["field_id"])) &
                  (pool["year"].astype(int) == int(y)) &
                  (pool["truth_positive"])]
        if hq.empty:
            continue
        h = hq.iloc[0]

        c = hm["geometry"].representative_point()
        heading = _bearing_v0f(float(exact.lat), float(exact.lon), float(c.y), float(c.x))

        rec = dict(f)
        rec.update(
            geometry=hm["geometry"],
            year=int(y),
            crop=h["crop"],
            truth_positive=True,
            rape_any=True,
            minne_source=h["minne_source"],
            meta_status=exact.status,
            meta_date=exact.date,
            pano_id=exact.pano_id,
            pano_lat=exact.lat,
            pano_lon=exact.lon,
            query_lat=exact.query_lat,
            query_lon=exact.query_lon,
            pano_boundary_dist_m=float(exact.dist_query_to_pano_m),
            heading_deg=heading,
            hist_share_current_pct=hm["hist_share_current_pct"],
            hist_share_hist_pct=hm["hist_share_hist_pct"],
            hist_second_share_current_pct=hm["hist_second_share_current_pct"],
            hist_grdkod_mar=hm["hist_grdkod_mar"],
            hist_skiftesbeteckning=hm["hist_skiftesbeteckning"],
            hist_source=hm["hist_source"],
        )
        # Closer panorama first; larger/more road-accessible fields break ties.
        rec["meta_score"] = 1000.0 - 8.0 * rec["pano_boundary_dist_m"]
        rec["total_score"] = rec["meta_score"] + float(f["base_score"])
        records.append(rec)

        print(f"  GOLD {len(records):02d}: {municipality} {y}-05  "
              f"dist={rec['pano_boundary_dist_m']:.1f} m  field={f['field_id']}")

        # We want a buffer so final 10 can be ranked rather than first 10 found.
        if len(records) >= 30:
            print(f"  30 gold candidates found after {i} fields; stopping scan and ranking best 10.")
            break

        if i % 100 == 0:
            print(f"  checked {i}/{len(fields)}; exact-maj+rapsår={exact_may}, strict-gold={len(records)}")

    if not records:
        return gpd.GeoDataFrame(columns=list(fields.columns), geometry="geometry", crs=4326)

    d = gpd.GeoDataFrame(records, geometry="geometry", crs=4326)
    d = d.sort_values(["pano_boundary_dist_m", "base_score"], ascending=[True, False])
    # Diversity: max 2 cases per municipality, then fill if fewer than 10.
    picked = []
    counts = {}
    for idx, r in d.iterrows():
        m = str(r["municipality"])
        if counts.get(m, 0) >= 2:
            continue
        picked.append(idx)
        counts[m] = counts.get(m, 0) + 1
        if len(picked) >= 10:
            break
    if len(picked) < 10:
        for idx in d.index:
            if idx in picked:
                continue
            picked.append(idx)
            if len(picked) >= 10:
                break
    return d.loc[picked].copy()
'''

needle = 'def candidate_pool(minne: pd.DataFrame, access_gdf):\n'
if needle not in s:
    raise SystemExit("FEL: candidate_pool hittades inte.")
s = s.replace(needle, HELPERS + '\n' + needle, 1)

# Replace v0f MAY-GOLD selection block with whole-Skåne positive hunt.
start = s.find('    if not api_key:\n        raise RuntimeError("v0f MAY-GOLD kräver Google metadata-API.")')
end = s.find('    meta.save()', start)
if start < 0 or end < 0:
    raise SystemExit("FEL: v0f selection block hittades inte.")

newblock = '''    if not api_key:\n        raise RuntimeError("v0g Skåne Positive Hunt kräver Google metadata-API.")\n    cache_path = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_stopa\\metadata_cache.json")\n    meta = StreetViewMetadata(api_key, cache_path)\n    print("Urvalsregel v0g: hela Skåne, ÅkerMinne=Raps (höst), Street View exakt maj samma år, historisk symmetrisk 1:1 >=95%, pano <=25 m.")\n    gold = discover_positive_gold_v0g(pool, meta, max_fields=20000)\n    if gold is None or len(gold) == 0:\n        raise RuntimeError("Inga positiva MAY-GOLD-fall hittades i Skåne.")\n    selected_parts = [gold]\n    print(f"\\nSKÅNE POSITIVE HUNT: valda {len(gold)}/10 guldkandidater.")\n    print("  per kommun:", gold["municipality"].value_counts().to_dict())\n    print("  år:", gold["year"].value_counts().sort_index().to_dict())\n    print("  panoavstånd m:", [round(float(x),1) for x in gold["pano_boundary_dist_m"]])\n'''
s = s[:start] + newblock + s[end:]

# Positive-only IDs and separate localStorage.
s = s.replace('d["case_id"] = [f"MG{i:02d}" for i in range(1, len(d) + 1)]',
              'd["case_id"] = [f"GOLD{i:02d}" for i in range(1, len(d) + 1)]', 1)
s = s.replace("const STORE='akerminne_streetview_may_gold_v0f_answers';",
              "const STORE='akerminne_streetview_positive_hunt_v0g_answers';", 1)

# UI wording.
s = s.replace('STOPPUNKT F — MAY-GOLD blind validering: Trelleborg + Skurup',
              'STOPPUNKT G — SKÅNE POSITIVE HUNT: 10 guldgula höstrapsfält', 1)
s = s.replace(
    'Varje fall har ett <b>Street View-pano från maj exakt målår</b> och ett historiskt skifte med strikt 1:1-geometri. Länken öppnar exakt panorama-ID och kameran riktas mot det historiska fältet. Bedöm RAPS / INTE RAPS / OSÄKER / INGEN BILD. ÅkerMinnes gröda är dold tills du scorear.',
    'Alla fall är <b>ÅkerMinne=Raps (höst)</b> men detta hålls dolt tills du scorear. Street View är från <b>maj exakt samma år</b>, historisk geometri är strikt 1:1 och panorama ligger nära fältet. <b>RAPS = sammanhängande gul blomning över odlad yta. Spridda gula maskrosor i gräs/vall = INTE RAPS.</b>', 1)
s = s.replace(
    'Urvalet är ett MAY-GOLD case-control-QA (upp till 10 positiva och 10 negativa), inte ett prevalensestimat.',
    'Urvalet är ett riktat positivt QA-test: endast ÅkerMinne=Raps (höst). Målet är 10 visuellt starka majfall, inte ett prevalensestimat.', 1)

# Score wording for positive-only test.
s = s.replace('Bedömbara binära fall:', 'Bedömbara positiva höstrapsfall:', 1)

s = s.replace('"version": "v0f"', '"version": "v0g"', 1)
s = s.replace(
    '"method": "MAY-GOLD: exact-May Street View pano, exact panorama ID, historical field polygon for capture year, symmetric 1:1 overlap >=95%, panorama <=15 m from historical field; blind review; no imagery downloaded.",',
    '"method": "SKANE POSITIVE HUNT: AkerMinne winter-rape positives only; exact-May Street View pano in same year; exact pano ID; historical field polygon; symmetric 1:1 overlap >=95%; panorama <=25 m; blind review; no imagery downloaded.",', 1)

DST.write_text(s, encoding="utf-8")

BAT_TEXT = r'''@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  AkerMinne x Street View - STOPPUNKT G v0g
echo  SKANE POSITIVE HUNT - 10 gold-yellow winter-rape fields
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

python src\akerminne_streetview_positive_hunt_v0g.py
if errorlevel 1 goto :fail

start "" "C:\AkerSync-AkerAccess\work\akerminne_streetview_positive_hunt_v0g\review.html"
echo.
echo KLART. De basta guldkandidaterna oppnas nu.
pause
exit /b 0

:fail
echo.
echo KORNINGEN MISSLYCKADES. Kopiera CMD-outputen till ChatGPT.
pause
exit /b 1
'''
BAT.write_text(BAT_TEXT, encoding="utf-8", newline="\r\n")

print("OK: v0g Skåne Positive Hunt skapad utan att skriva över v0f.")
print(f"  Script: {DST}")
print(f"  Kör:    {BAT}")
print(r"  Output: C:\AkerSync-AkerAccess\work\akerminne_streetview_positive_hunt_v0g")
