#!/usr/bin/env python3
"""ÅkerPuls 2026 preliminary fields: STOPPUNKT A0 preflight (no mass download)."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, subprocess, urllib.parse, urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG_PATH=ROOT/'config'/'akerpuls_prelim_fields_2026_v0.json'


def sha256_file(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def validate_config(c):
    exp={'S2_2026_APRIL':['2026-04-08','2026-04-09'],'S2_2026_MAY':['2026-05-25'],
         'S2_2026_JUNE':['2026-06-26','2026-06-27'],'S2_2026_JULY':['2026-07-09']}
    if c.get('schema_version')!='akerpuls-prelim-fields-2026-v0' or c.get('snapshots')!=exp: raise RuntimeError('Frozen snapshot contract changed')
    s=c['sentinel2']
    if s['pair_rule']!='clear_pixel_first_then_lowest_CLD; never average across paired dates': raise RuntimeError('Pair rule changed')
    if set(s['valid_scl_codes'])|set(s['excluded_scl_codes'])!=set(range(12)): raise RuntimeError('SCL partition invalid')
    if any(c['scope_guards'].values()): raise RuntimeError('Scope guard changed')


def cfg_load():
    c=json.loads(CFG_PATH.read_text(encoding='utf-8')); validate_config(c); return c


def git_check(c):
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    if branch!=c['feature_branch']: raise RuntimeError(f'Expected {c["feature_branch"]}, got {branch}')
    if subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True).strip(): raise RuntimeError('Working tree not clean')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(); base=c['upstream_freeze']['commit']
    if subprocess.run(['git','merge-base','--is-ancestor',base,head],cwd=ROOT).returncode: raise RuntimeError('Frozen base is not ancestor')
    return branch,head


def stac(c,bbox,day):
    d=date.fromisoformat(day); e=d+timedelta(days=1)
    body=json.dumps({'collections':[c['sentinel2']['collection']],'bbox':bbox,'datetime':f'{d}T00:00:00Z/{e}T00:00:00Z','limit':100}).encode()
    req=urllib.request.Request(c['sentinel2']['stac_search_url'],data=body,method='POST',headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as r: return json.loads(r.read())['features']


def token(c):
    i=os.getenv('CDSE_CLIENT_ID','').strip(); s=os.getenv('CDSE_CLIENT_SECRET','').strip()
    if not i or not s: raise RuntimeError('BLOCKED_CREDENTIALS: CDSE_CLIENT_ID/CDSE_CLIENT_SECRET not set')
    body=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':i,'client_secret':s}).encode()
    req=urllib.request.Request(c['sentinel2']['token_url'],data=body,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read())['access_token']


def smoke(c,tok,x,y):
    day='2026-05-25'; nxt='2026-05-26'
    ev='//VERSION=3\nfunction setup(){return {input:[{bands:["B04","B08","SCL","CLD","dataMask"]}],output:{bands:5,sampleType:"FLOAT32"}};}\nfunction evaluatePixel(s){return [s.B04,s.B08,s.SCL,s.CLD,s.dataMask];}'
    p={'input':{'bounds':{'bbox':[x-160,y-160,x+160,y+160],'properties':{'crs':'http://www.opengis.net/def/crs/EPSG/0/32633'}},'data':[{'type':c['sentinel2']['collection'],'dataFilter':{'timeRange':{'from':day+'T00:00:00Z','to':nxt+'T00:00:00Z'},'maxCloudCoverage':100}}]},'output':{'width':32,'height':32,'responses':[{'identifier':'default','format':{'type':'image/tiff'}}]},'evalscript':ev}
    req=urllib.request.Request(c['sentinel2']['process_url'],data=json.dumps(p).encode(),method='POST',headers={'Authorization':'Bearer '+tok,'Content-Type':'application/json','Accept':'image/tiff'})
    with urllib.request.urlopen(req,timeout=120) as r:
        b=r.read(); pu=r.headers.get('x-processingunits-spent')
    return {'status':'PASS','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'pu':pu,'payload_persisted':False}


def write_csv(p,rows):
    if not rows: return
    with open(p,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def main():
    import geopandas as gpd
    from shapely.geometry import shape, box
    from shapely.ops import unary_union
    a=argparse.ArgumentParser(); a.add_argument('--local-paths',default=str(ROOT/'config'/'local_paths.json')); a.add_argument('--output-dir'); z=a.parse_args()
    c=cfg_load(); branch,head=git_check(c); out=Path(z.output_dir or c['outputs']['preflight_dir']); out.mkdir(parents=True,exist_ok=True)
    lp=json.loads(Path(z.local_paths).read_text(encoding='utf-8-sig')); fp=Path(lp['skiften'])
    if not fp.is_file(): raise FileNotFoundError(fp)
    sh=sha256_file(fp); fr=c['upstream_freeze']
    if sh!=fr['expected_2025_geometry_sha256']: raise RuntimeError('Frozen 2025 geometry SHA256 mismatch')
    g=gpd.read_file(fp)
    if len(g)!=fr['expected_2025_fields']: raise RuntimeError(f'Expected {fr["expected_2025_fields"]} fields, got {len(g)}')
    g=g.to_crs(epsg=32633); fu=g.geometry.union_all() if hasattr(g.geometry,'union_all') else g.geometry.unary_union
    bbox4326=list(map(float,g.to_crs(epsg=4326).total_bounds)); area_ha=fu.area/10000
    side=c['tiling']['tile_pixels']*c['sentinel2']['resolution_m']; buf=fu.buffer(c['tiling']['field_buffer_m']); b=buf.bounds
    xs=range(math.floor(b[0]/side)*side,math.ceil(b[2]/side)*side,side); ys=range(math.floor(b[1]/side)*side,math.ceil(b[3]/side)*side,side)
    tiles=[]
    for y in ys:
        for x in xs:
            q=box(x,y,x+side,y+side)
            if q.intersects(buf): tiles.append({'tile_id':f'E{x:07d}_N{y:07d}','minx':x,'miny':y,'maxx':x+side,'maxy':y+side})
    write_csv(out/'tile_plan.csv',tiles)
    gpd.GeoDataFrame(tiles,geometry=[box(r['minx'],r['miny'],r['maxx'],r['maxy']) for r in tiles],crs='EPSG:32633').to_file(out/'tile_plan.gpkg',layer='stopA_tiles',driver='GPKG')
    scenes=[]; daily={}; snap=[]
    for name,days in c['snapshots'].items():
        unions=[]
        for day in days:
            items=stac(c,bbox4326,day); gg=gpd.GeoSeries([shape(i['geometry']) for i in items],crs='EPSG:4326').to_crs(epsg=32633) if items else None
            u=(gg.union_all() if hasattr(gg,'union_all') else gg.unary_union) if items else None; daily[day]=u; unions += ([u] if u is not None else [])
            for i in items:
                p=i.get('properties',{}); scenes.append({'snapshot':name,'date':day,'item_id':i.get('id',''),'datetime':p.get('datetime',''),'eo_cloud_cover':p.get('eo:cloud_cover','')})
        su=unary_union(unions) if unions else None; cov=0 if su is None else fu.intersection(su).area/fu.area
        snap.append({'snapshot':name,'dates':'+'.join(days),'field_union_coverage_percent':round(100*cov,4)})
    write_csv(out/'scene_inventory.csv',scenes); write_csv(out/'snapshot_coverage.csv',snap)
    counted=len(c['sentinel2']['bands_stopA'])+2; pu_tile=(c['tiling']['tile_pixels']/512)**2*counted/3
    reqs=sum(sum(1 for r in tiles if u is not None and box(r['minx'],r['miny'],r['maxx'],r['maxy']).intersects(u)) for u in daily.values())
    pu=round(reqs*pu_tile,2); guard='PASS' if reqs<=c['resource_guard']['maximum_planned_requests'] and pu<=c['resource_guard']['maximum_planned_pu'] else 'BLOCKED'
    rp=fu.representative_point(); sm=smoke(c,token(c),float(rp.x),float(rp.y))
    status='PASS' if guard=='PASS' and all(r['field_union_coverage_percent']>=99 for r in snap) else 'REVIEW'
    m={'schema_version':'akerpuls-prelim-fields-2026-stopa0-v1','status':status,'generated_utc':datetime.now(timezone.utc).isoformat(),'git':{'branch':branch,'head':head,'upstream_commit':fr['commit']},'frozen_geometry':{'path':str(fp.resolve()),'sha256':sh,'rows':len(g),'field_union_area_ha':round(area_ha,3)},'snapshot_coverage':snap,'tile_plan':{'tiles':len(tiles),'tile_pixels':c['tiling']['tile_pixels'],'resolution_m':10},'resource_estimate':{'requests':reqs,'estimated_pu_upper':pu,'counted_input_bands':counted},'resource_guard':guard,'process_api_smoke':sm,'next_step':'STOPPUNKT A mosaic build not executed in A0','scope':c['scope_guards']}
    (out/'preflight_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# ÅkerPuls 2026 – STOPPUNKT A0',f'- Status: **{status}**',f'- 2025 fields: {len(g):,}; union area {area_ha:,.1f} ha; SHA256 PASS',f'- Tiles: {len(tiles)}',f'- Planned requests: {reqs}',f'- Estimated PU upper: {pu}',f'- Resource guard: **{guard}**',f'- Process API smoke: **{sm["status"]}**','','## Snapshot footprint coverage']+[f'- {r["snapshot"]}: {r["field_union_coverage_percent"]:.4f}% ({r["dates"]})' for r in snap]+['','No Sentinel-2 mosaic pixels were mass-downloaded in A0.']
    (out/'preflight_qa.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('AKERPULS PRELIM FIELDS 2026 - STOPPUNKT A0 PREFLIGHT'); print('STATUS='+status); print(f'FIELDS_2025={len(g)}'); print(f'FIELD_UNION_AREA_HA={area_ha:.3f}')
    for r in snap: print(f'COVERAGE_{r["snapshot"]}={r["field_union_coverage_percent"]:.4f}%')
    print(f'TILES={len(tiles)}'); print(f'PLANNED_REQUESTS={reqs}'); print(f'ESTIMATED_PU_UPPER={pu}'); print('RESOURCE_GUARD='+guard); print(f'PROCESS_API_SMOKE={sm["status"]} PU={sm["pu"]}'); print('OUTPUT='+str(out)); print('NO_MASS_DOWNLOAD=TRUE')
    return 0 if guard=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
