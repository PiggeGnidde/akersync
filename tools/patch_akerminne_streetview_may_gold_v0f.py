from pathlib import Path
import shutil

P = Path(r"C:\AkerMinne_StreetView_STOPA\src\akerminne_streetview_stopa.py")
B = Path(r"C:\AkerMinne_StreetView_STOPA\RUN_STOPA.bat")
if not P.exists():
    raise SystemExit(f"FEL: Hittar inte {P}")
s = P.read_text(encoding="utf-8")
if '"version": "v0f"' in s:
    print("v0f finns redan; ingen ändring behövs.")
    raise SystemExit(0)
if '"version": "v0d"' not in s:
    raise SystemExit("FEL: Förväntade v0d. Stoppar utan att ändra filen.")

backup = P.with_suffix(".v0d_backup.py")
if not backup.exists():
    shutil.copy2(P, backup)

s = s.replace(
    'DEFAULT_OUT = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_stopa")',
    'DEFAULT_OUT = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_may_gold_v0f")', 1)
s = s.replace(
    'MUNICIPALITIES = {"trelleborg": {"pos": 15, "neg": 5}, "skurup": {"pos": 10, "neg": 5}}',
    'MUNICIPALITIES = {"trelleborg": {"pos": 5, "neg": 5}, "skurup": {"pos": 5, "neg": 5}}', 1)
s = s.replace('VALID_CAPTURE_MONTHS = (5, 6, 7)', 'VALID_CAPTURE_MONTHS = (5,)', 1)
s = s.replace('CAPTURE_MONTH_SCORE = {5: 300.0, 6: 180.0, 7: 80.0}', 'CAPTURE_MONTH_SCORE = {5: 300.0}', 1)
s = s.replace('MAX_PANO_BOUNDARY_M = 25.0', 'MAX_PANO_BOUNDARY_M = 15.0', 1)

HELPERS = r'''

# ---------------- v0f MAY-GOLD strict historical geometry ----------------
HIST_ROOT_V0F = Path(r"C:\AkerSyncRaw\akerminne_v1a")
HIST_CACHE_V0F = {}


def _load_hist_v0f(municipality: str, year: int):
    key = (norm_text(municipality), int(year))
    if key in HIST_CACHE_V0F:
        return HIST_CACHE_V0F[key]
    m = key[0]
    p = HIST_ROOT_V0F / str(year) / f"arslager_skifte_{m}_{year}.gpkg"
    if not p.exists():
        HIST_CACHE_V0F[key] = (None, str(p))
        return HIST_CACHE_V0F[key]
    g = gpd.read_file(p)
    if g.crs is None:
        raise ValueError(f"Historisk geometri saknar CRS: {p}")
    g = g.to_crs(3006)
    HIST_CACHE_V0F[key] = (g, str(p))
    return HIST_CACHE_V0F[key]


def _strict_hist_match_v0f(current_geom_wgs84, municipality: str, year: int):
    hist, source = _load_hist_v0f(municipality, int(year))
    if hist is None or hist.empty:
        return None
    current = gpd.GeoSeries([current_geom_wgs84], crs=4326).to_crs(3006).iloc[0]
    if current is None or current.is_empty or current.area <= 0:
        return None
    idx = list(hist.sindex.query(current, predicate="intersects"))
    pieces = []
    for j in idx:
        hr = hist.iloc[j]
        try:
            inter = current.intersection(hr.geometry)
            a = float(inter.area) if not inter.is_empty else 0.0
        except Exception:
            a = 0.0
        if a > 1.0:
            pieces.append((j, hr, a))
    if not pieces:
        return None
    pieces.sort(key=lambda z: z[2], reverse=True)
    _, top, a1 = pieces[0]
    a2 = pieces[1][2] if len(pieces) > 1 else 0.0
    share_current = 100.0 * a1 / float(current.area)
    share_hist = 100.0 * a1 / float(top.geometry.area) if top.geometry.area else 0.0
    second_current = 100.0 * a2 / float(current.area)
    strict = share_current >= 95.0 and share_hist >= 95.0 and second_current <= 3.0
    if not strict:
        return None
    hist_wgs = gpd.GeoSeries([top.geometry], crs=3006).to_crs(4326).iloc[0]
    code = top.get("grdkod_mar") if "grdkod_mar" in top.index else None
    label = top.get("skiftesbeteckning") if "skiftesbeteckning" in top.index else None
    return {
        "geometry": hist_wgs,
        "hist_share_current_pct": share_current,
        "hist_share_hist_pct": share_hist,
        "hist_second_share_current_pct": second_current,
        "hist_grdkod_mar": code,
        "hist_skiftesbeteckning": label,
        "hist_source": source,
    }


def _bearing_v0f(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _negative_priority_v0f(crop):
    n = crop_norm(crop)
    if "sockerbetor" in n:
        return 5
    if "korn" in n and "var" in n:
        return 4
    if "havre" in n:
        return 3
    if "vete" in n and "var" in n:
        return 3
    if "majs" in n:
        return 2
    return 1


def discover_may_gold_v0f(pool, meta: StreetViewMetadata, municipality: str, max_fields: int = 5000):
    q = pool[pool["municipality"] == municipality].copy()
    history = q.sort_values(["field_id", "year"]).drop_duplicates(["field_id", "year"], keep="last")
    hist = {(str(r.field_id), int(r.year)): r for r in history.itertuples(index=False)}
    fields = q.sort_values(["base_score", "field_id"], ascending=[False, True]).drop_duplicates("field_id").head(max_fields).copy()
    fields = gpd.GeoDataFrame(fields, geometry="geometry", crs=pool.crs).to_crs(4326)
    records = []
    pos = neg = 0
    for i, (_, f) in enumerate(fields.iterrows(), 1):
        first = query_best_capture_metadata(meta, f.geometry, n_points=5)
        y, mo = date_parts(first.date)
        if (first.status != "OK" or y not in TARGET_YEARS or mo != 5 or
                first.dist_query_to_pano_m is None or first.dist_query_to_pano_m > MAX_PANO_BOUNDARY_M):
            if i % 100 == 0:
                print(f"  {municipality} MAY-GOLD {i}/{len(fields)} fält; strict maj={len(records)}, höstraps={pos}, neg={neg}")
            continue

        h = hist.get((str(f["field_id"]), int(y)))
        if h is None:
            continue

        hm = _strict_hist_match_v0f(f.geometry, municipality, int(y))
        if hm is None:
            continue

        exact = query_best_capture_metadata(meta, hm["geometry"], n_points=8)
        y2, mo2 = date_parts(exact.date)
        if (exact.status != "OK" or y2 != int(y) or mo2 != 5 or
                exact.dist_query_to_pano_m is None or exact.dist_query_to_pano_m > MAX_PANO_BOUNDARY_M):
            continue

        c = hm["geometry"].representative_point()
        heading = _bearing_v0f(float(exact.lat), float(exact.lon), float(c.y), float(c.x))
        rec = dict(f)
        rec.update(
            geometry=hm["geometry"], year=int(y), crop=h.crop,
            truth_positive=bool(h.truth_positive), rape_any=bool(h.rape_any),
            minne_source=h.minne_source, meta_status=exact.status, meta_date=exact.date,
            pano_id=exact.pano_id, pano_lat=exact.lat, pano_lon=exact.lon,
            query_lat=exact.query_lat, query_lon=exact.query_lon,
            pano_boundary_dist_m=float(exact.dist_query_to_pano_m), heading_deg=heading,
            hist_share_current_pct=hm["hist_share_current_pct"],
            hist_share_hist_pct=hm["hist_share_hist_pct"],
            hist_second_share_current_pct=hm["hist_second_share_current_pct"],
            hist_grdkod_mar=hm["hist_grdkod_mar"],
            hist_skiftesbeteckning=hm["hist_skiftesbeteckning"],
            hist_source=hm["hist_source"],
            neg_priority=_negative_priority_v0f(h.crop),
        )
        rec["meta_score"] = 500.0 - 4.0 * rec["pano_boundary_dist_m"]
        rec["total_score"] = float(f["base_score"]) + rec["meta_score"]
        records.append(rec)
        if rec["truth_positive"]:
            pos += 1
        elif not rec["rape_any"]:
            neg += 1
        if i % 100 == 0:
            print(f"  {municipality} MAY-GOLD {i}/{len(fields)} fält; strict maj={len(records)}, höstraps={pos}, neg={neg}")
        if pos >= 8 and neg >= 20:
            print(f"  {municipality}: tillräcklig MAY-GOLD-buffer efter {i} fält.")
            break
    if not records:
        return gpd.GeoDataFrame(columns=list(fields.columns), geometry="geometry", crs=4326)
    return gpd.GeoDataFrame(records, geometry="geometry", crs=4326)


def select_may_gold_global_v0f(cands, n_pos: int = 10, n_neg: int = 10):
    if cands is None or len(cands) == 0:
        return cands, cands
    d = cands.copy()
    d = d.sort_values(["pano_boundary_dist_m", "base_score"], ascending=[True, False])
    pos = d[d["truth_positive"]].drop_duplicates("field_id").head(n_pos).copy()
    neg = d[~d["rape_any"]].copy()
    neg = neg.sort_values(["neg_priority", "pano_boundary_dist_m", "base_score"], ascending=[False, True, False])
    neg = neg.drop_duplicates("field_id").head(n_neg).copy()
    return pos, neg
'''

needle = 'def candidate_pool(minne: pd.DataFrame, access_gdf):\n'
if needle not in s:
    raise SystemExit("FEL: candidate_pool hittades inte; stoppar.")
s = s.replace(needle, HELPERS + '\n' + needle, 1)

start = s.find('    meta = StreetViewMetadata(api_key, outdir / "metadata_cache.json")')
end = s.find('    meta.save()', start)
if start < 0 or end < 0:
    raise SystemExit("FEL: v0d selection block hittades inte; stoppar.")
newblock = '''    if not api_key:\n        raise RuntimeError("v0f MAY-GOLD kräver Google metadata-API.")\n    cache_path = Path(r"C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_stopa\\metadata_cache.json")\n    meta = StreetViewMetadata(api_key, cache_path)\n    print("Urvalsregel v0f MAY-GOLD: exakt maj + historisk geometri samma år + symmetrisk 1:1 >=95% + pano <=15 m.")\n    direct_parts = []\n    for m in MUNICIPALITIES:\n        print(f"\\n--- {m.title()} MAY-GOLD ---")\n        direct = discover_may_gold_v0f(pool, meta, m, max_fields=5000)\n        direct_parts.append(direct)\n        if len(direct):\n            print(f"  hittade {len(direct)} strict-majfall; höstraps={int(direct['truth_positive'].sum())}, negativa={int((~direct['rape_any']).sum())}")\n    nonempty = [x for x in direct_parts if x is not None and len(x)]\n    if not nonempty:\n        raise RuntimeError("Inga MAY-GOLD-fall hittades.")\n    all_direct = gpd.GeoDataFrame(pd.concat(nonempty, ignore_index=True), geometry="geometry", crs=4326)\n    p, n = select_may_gold_global_v0f(all_direct, 10, 10)\n    selected_parts = [p, n]\n    print(f"\\nMAY-GOLD valda: höstraps={len(p)}/10, negativa={len(n)}/10, totalt={len(p)+len(n)}")\n    if len(p):\n        print("  positiva per kommun:", p['municipality'].value_counts().to_dict())\n    if len(n):\n        print("  negativa grödor:", n['crop'].value_counts().to_dict())\n'''
s = s[:start] + newblock + s[end:]

old_url = '''    params = {"api": "1", "map_action": "pano", "viewpoint": f"{lat:.7f},{lon:.7f}"}\n    return "https://www.google.com/maps/@?" + urlencode(params)'''
new_url = '''    params = {"api": "1", "map_action": "pano", "viewpoint": f"{lat:.7f},{lon:.7f}"}\n    pano = row.get("pano_id")\n    if pano is not None and not pd.isna(pano) and str(pano):\n        params["pano"] = str(pano)\n    heading = row.get("heading_deg")\n    if heading is not None and not pd.isna(heading):\n        params["heading"] = f"{float(heading):.1f}"\n    params["fov"] = "90"\n    return "https://www.google.com/maps/@?" + urlencode(params)'''
if old_url not in s:
    raise SystemExit("FEL: streetview_url hittades inte; stoppar.")
s = s.replace(old_url, new_url, 1)

s = s.replace('d["case_id"] = [f"SV{i:02d}" for i in range(1, len(d) + 1)]',
              'd["case_id"] = [f"MG{i:02d}" for i in range(1, len(d) + 1)]', 1)
s = s.replace("const STORE='akerminne_streetview_stopa_answers_v1';",
              "const STORE='akerminne_streetview_may_gold_v0f_answers';", 1)

s = s.replace('STOPPUNKT A — blind validering: Trelleborg + Skurup',
              'STOPPUNKT F — MAY-GOLD blind validering: Trelleborg + Skurup', 1)
s = s.replace('Öppna Street View. Bedöm <b>endast bilden</b>. Om bilden inte är från målåret, använd <i>See more dates / Visa fler datum</i> och välj målåret. Klicka sedan RAPS / INTE RAPS / OSÄKER / INGEN BILD. ÅkerMinnes gröda är dold tills du scorear.',
              'Varje fall har ett <b>Street View-pano från maj exakt målår</b> och ett historiskt skifte med strikt 1:1-geometri. Länken öppnar exakt panorama-ID och kameran riktas mot det historiska fältet. Bedöm RAPS / INTE RAPS / OSÄKER / INGEN BILD. ÅkerMinnes gröda är dold tills du scorear.', 1)
s = s.replace('Urvalet är stratifierat case-control (25 positiva, 10 negativa), så detta är ett QA-test — inte ett prevalensestimat.',
              'Urvalet är ett MAY-GOLD case-control-QA (upp till 10 positiva och 10 negativa), inte ett prevalensestimat.', 1)

old_truth = '''            "total_score": json_safe(r.get("total_score")),\n        })'''
new_truth = '''            "total_score": json_safe(r.get("total_score")),\n            "pano_boundary_dist_m": json_safe(r.get("pano_boundary_dist_m")),\n            "hist_share_current_pct": json_safe(r.get("hist_share_current_pct")),\n            "hist_share_hist_pct": json_safe(r.get("hist_share_hist_pct")),\n            "hist_second_share_current_pct": json_safe(r.get("hist_second_share_current_pct")),\n            "hist_grdkod_mar": json_safe(r.get("hist_grdkod_mar")),\n            "hist_skiftesbeteckning": json_safe(r.get("hist_skiftesbeteckning")),\n            "hist_source": json_safe(r.get("hist_source")),\n            "heading_deg": json_safe(r.get("heading_deg")),\n        })'''
if old_truth not in s:
    raise SystemExit("FEL: truth-outputblocket hittades inte; stoppar.")
s = s.replace(old_truth, new_truth, 1)

s = s.replace('"version": "v0d"', '"version": "v0f"', 1)
s = s.replace(
    '"method": "Street View metadata date first; May-July only within 25 m of field boundary; compare frozen AkerMinne on same field and exact capture year; blind review; no imagery downloaded.",',
    '"method": "MAY-GOLD: exact-May Street View pano, exact panorama ID, historical field polygon for capture year, symmetric 1:1 overlap >=95%, panorama <=15 m from historical field; blind review; no imagery downloaded.",', 1)

P.write_text(s, encoding="utf-8")

if B.exists():
    b = B.read_text(encoding="utf-8", errors="replace")
    b = b.replace("STOPPUNKT A v0d", "STOPPUNKT F v0f MAY-GOLD")
    b = b.replace(r"C:\AkerSync-AkerAccess\work\akerminne_streetview_stopa\review.html",
                  r"C:\AkerSync-AkerAccess\work\akerminne_streetview_may_gold_v0f\review.html")
    B.write_text(b, encoding="utf-8")

print("OK: v0f MAY-GOLD installerad på plats.")
print("Gamla STOPA-resultat sparas; ny output: C:\\AkerSync-AkerAccess\\work\\akerminne_streetview_may_gold_v0f")
print("Regel: maj exakt målår, historisk polygon, symmetrisk 1:1 >=95%, pano <=15 m, exakt pano-ID.")
