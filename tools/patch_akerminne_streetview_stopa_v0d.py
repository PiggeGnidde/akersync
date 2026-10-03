from pathlib import Path
import sys

P = Path(r"C:\AkerMinne_StreetView_STOPA\src\akerminne_streetview_stopa.py")
if not P.exists():
    raise SystemExit(f"FEL: Hittar inte {P}")
s = P.read_text(encoding="utf-8")
if '"version": "v0d"' in s:
    print("v0d finns redan; ingen ändring behövs.")
    raise SystemExit(0)
if '"version": "v0c"' not in s:
    raise SystemExit("FEL: Förväntade v0c. Stoppar utan att ändra filen.")

s = s.replace(
    'TARGET_YEARS = set(range(2015, 2026))\n',
    'TARGET_YEARS = set(range(2015, 2026))\nVALID_CAPTURE_MONTHS = (5, 6, 7)\nCAPTURE_MONTH_SCORE = {5: 300.0, 6: 180.0, 7: 80.0}\nMAX_PANO_BOUNDARY_M = 25.0\n',
    1,
)

HELPERS = r'''

def capture_metadata_score(hit: MetaHit) -> float:
    # Direct validation: May is gold, June good, July fallback.
    if hit.status != "OK":
        return -1e9
    y, m = date_parts(hit.date)
    if y not in TARGET_YEARS or m not in VALID_CAPTURE_MONTHS:
        return -1e8
    d = hit.dist_query_to_pano_m
    if d is None or d > MAX_PANO_BOUNDARY_M:
        return -1e7
    return CAPTURE_MONTH_SCORE[m] + max(0.0, 60.0 - 2.0 * float(d))


def query_best_capture_metadata(meta: StreetViewMetadata, geom_wgs84, n_points: int = 5) -> MetaHit:
    hits, seen = [], set()
    for p in sample_boundary_points(geom_wgs84, n=n_points):
        h = meta.query(float(p.y), float(p.x), radius=50)
        if h.pano_id and h.pano_id in seen:
            continue
        if h.pano_id:
            seen.add(h.pano_id)
        hits.append(h)
    if not hits:
        c = geom_wgs84.representative_point()
        return MetaHit(status="NO_POINTS", query_lat=float(c.y), query_lon=float(c.x))
    return max(hits, key=capture_metadata_score)


def discover_direct_cases(pool, meta: StreetViewMetadata, municipality: str, need_pos: int, need_neg: int, max_fields: int = 1200):
    # Invert search: Street View capture date chooses the ÅkerMinne year.
    q = pool[pool["municipality"] == municipality].copy()
    history = q.sort_values(["field_id", "year"]).drop_duplicates(["field_id", "year"], keep="last")
    hist = {(str(r.field_id), int(r.year)): r for r in history.itertuples(index=False)}
    fields = q.sort_values(["base_score", "field_id"], ascending=[False, True]).drop_duplicates("field_id").head(max_fields).copy()
    fields = gpd.GeoDataFrame(fields, geometry="geometry", crs=pool.crs).to_crs(4326)
    records, pos, neg = [], 0, 0
    for i, (_, f) in enumerate(fields.iterrows(), 1):
        hit = query_best_capture_metadata(meta, f.geometry, n_points=5)
        y, m = date_parts(hit.date)
        ok = (hit.status == "OK" and y in TARGET_YEARS and m in VALID_CAPTURE_MONTHS
              and hit.dist_query_to_pano_m is not None and hit.dist_query_to_pano_m <= MAX_PANO_BOUNDARY_M)
        if ok:
            h = hist.get((str(f["field_id"]), int(y)))
            if h is not None:
                rec = dict(f)
                rec.update(year=int(y), crop=h.crop, truth_positive=bool(h.truth_positive), rape_any=bool(h.rape_any),
                           minne_source=h.minne_source, meta_status=hit.status, meta_date=hit.date,
                           pano_id=hit.pano_id, pano_lat=hit.lat, pano_lon=hit.lon,
                           query_lat=hit.query_lat, query_lon=hit.query_lon,
                           pano_boundary_dist_m=hit.dist_query_to_pano_m,
                           meta_score=capture_metadata_score(hit))
                rec["total_score"] = float(f["base_score"]) + rec["meta_score"]
                records.append(rec)
                if rec["truth_positive"]: pos += 1
                elif not rec["rape_any"]: neg += 1
        if i % 50 == 0:
            print(f"  {municipality} StreetView {i}/{len(fields)} fält; användbara maj-jul={len(records)}, höstraps={pos}, neg={neg}")
        if pos >= max(need_pos * 2, need_pos + 8) and neg >= max(need_neg * 3, need_neg + 12):
            print(f"  {municipality}: tillräcklig direkt-träffpool efter {i} fält.")
            break
    if not records:
        return gpd.GeoDataFrame(columns=list(fields.columns), geometry="geometry", crs=4326)
    return gpd.GeoDataFrame(records, geometry="geometry", crs=4326)


def select_direct_cases(cands, n_pos: int, n_neg: int):
    if cands is None or len(cands) == 0:
        return cands, cands
    d = cands.copy()
    d["capture_month"] = d["meta_date"].map(lambda x: date_parts(x)[1])
    d["month_rank"] = d["capture_month"].map({5: 3, 6: 2, 7: 1}).fillna(0)
    d = d.sort_values(["month_rank", "pano_boundary_dist_m", "base_score"], ascending=[False, True, False])
    pos = d[d["truth_positive"]].head(n_pos).copy()
    neg = d[~d["rape_any"]].head(n_neg).copy()
    return pos, neg
'''
needle = 'def candidate_pool(minne: pd.DataFrame, access_gdf):\n'
if needle not in s:
    raise SystemExit("FEL: candidate_pool hittades inte; stoppar.")
s = s.replace(needle, HELPERS + '\n' + needle, 1)

OLD = '''    meta = StreetViewMetadata(api_key, outdir / "metadata_cache.json")
    selected_parts = []
    for m, counts in MUNICIPALITIES.items():
        print(f"\\n--- {m.title()} ---")
        # Probe enough to give the metadata date a chance to find exact-year gold cases.
        sp = score_top_pool(pool, meta, m, True, n_probe=max(counts["pos"] * 3, 40))
        sn = score_top_pool(pool, meta, m, False, n_probe=max(counts["neg"] * 6, 30))
        p, n = select_cases(sp, sn, m, counts["pos"], counts["neg"])
        if len(p) < counts["pos"] or len(n) < counts["neg"]:
            print(f"VARNING: {m}: fick {len(p)}/{counts['pos']} positiva och {len(n)}/{counts['neg']} negativa")
        selected_parts.extend([p, n])
        exact = sum(date_parts(x)[0] == int(y) for x, y in zip(pd.concat([p,n])["meta_date"], pd.concat([p,n])["year"]) if x)
        print(f"Valda {len(p)+len(n)} fall; nuvarande metadata exakt målår: {exact}")
'''
NEW = '''    meta = StreetViewMetadata(api_key, outdir / "metadata_cache.json")
    selected_parts = []
    if not api_key:
        raise RuntimeError("v0d kräver Google metadata-API.")
    print("Urvalsregel v0d: Street View-datum först -> ÅkerMinne samma fält+samma år; endast maj-juli, maj prioriteras, <=25 m från fältgräns.")
    for m, counts in MUNICIPALITIES.items():
        print(f"\\n--- {m.title()} ---")
        direct = discover_direct_cases(pool, meta, m, counts["pos"], counts["neg"], max_fields=1200)
        p, n = select_direct_cases(direct, counts["pos"], counts["neg"])
        if len(p) < counts["pos"] or len(n) < counts["neg"]:
            print(f"VARNING: {m}: endast {len(p)}/{counts['pos']} höstraps och {len(n)}/{counts['neg']} negativa med användbar maj-juli-bild. Fyller INTE med dåliga månader.")
        selected_parts.extend([p, n])
        if len(p) + len(n):
            dates = pd.concat([p, n])["meta_date"].value_counts().sort_index().to_dict()
            print(f"Valda {len(p)+len(n)} direkt-träffar; datumfördelning: {dates}")
'''
if OLD not in s:
    raise SystemExit("FEL: v0c urvalsblock hittades inte; stoppar.")
s = s.replace(OLD, NEW, 1)
s = s.replace('"version": "v0c"', '"version": "v0d"', 1)
s = s.replace(
    '"method": "Frozen AkerAccess roadside ranking + frozen AkerMinne field-years; blind human review. Google API used for metadata only, no imagery downloaded.",',
    '"method": "Street View metadata date first; May-July only within 25 m of field boundary; compare frozen AkerMinne on same field and exact capture year; blind review; no imagery downloaded.",',
    1,
)
P.write_text(s, encoding="utf-8")
B = Path(r"C:\\AkerMinne_StreetView_STOPA\\RUN_STOPA.bat")
if B.exists():
    b = B.read_text(encoding="utf-8", errors="replace")
    b = b.replace("STOPPUNKT A v0c", "STOPPUNKT A v0d")
    B.write_text(b, encoding="utf-8")
print("OK: v0d installerad på plats.")
print("Ny metod: Street View-datum -> samma ÅkerMinne-år; maj > juni > juli; andra månader kasseras.")
