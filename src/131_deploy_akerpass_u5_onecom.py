#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy exact ÅkerPass unified RC1 ZIP to password-protected one.com preview.

Safety:
- verifies fixed RC1 SHA256 and manifest,
- pins SFTP host key,
- requires existing preview .htaccess + .htpasswd,
- stages upload behind a deny-all .htaccess,
- preserves auth files byte-for-byte,
- keeps the previous preview in a deny-all rollback folder until U6,
- runs hosted HTTPS smoke; automatic rollback on smoke failure.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import posixpath
import socket
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

import paramiko

ROOT=Path(__file__).resolve().parents[1]
ENV_PATH=ROOT/".env"
RC_MANIFEST=ROOT/"work"/"akerpass_unified_rc1"/"akerpass_unified_preview_v0a_r1_rc1_manifest.json"
RECEIPT_DIR=ROOT/"work"/"akerpass_u5_deploy"
RECEIPT=RECEIPT_DIR/"u5_deploy_receipt.json"

EXPECTED_RELEASE="akerpass-unified-preview-v0a-r1-rc1"
EXPECTED_ZIP_SHA="01a96dda7ced90be99a686f8de081ed72fc19f0fd4b1adf556d42de7def48173"
PROTECTED={".htaccess",".htpasswd"}
DENY_ALL=b"Require all denied\n"

def read_env()->dict[str,str]:
    out={}
    if not ENV_PATH.is_file():
        raise FileNotFoundError(".env missing. Run SETUP_AKERPASS_U5_ONECOM.bat first.")
    for raw in ENV_PATH.read_text(encoding="utf-8",errors="replace").splitlines():
        s=raw.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k,v=s.split("=",1);out[k.strip()]=v.strip()
    return out

def b64d(s:str)->str:
    return base64.b64decode(s.encode("ascii")).decode("utf-8")

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def sha256_bytes(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def hostkey_sha256(key:paramiko.PKey)->str:
    d=hashlib.sha256(key.asbytes()).digest()
    return "SHA256:"+base64.b64encode(d).decode("ascii").rstrip("=")

def connect(env:dict[str,str]):
    host=env["AKERPASS_SFTP_HOST"];port=int(env.get("AKERPASS_SFTP_PORT","22"))
    user=env["AKERPASS_SFTP_USER"];password=b64d(env["AKERPASS_SFTP_PASSWORD_B64"])
    sock=socket.create_connection((host,port),timeout=30)
    t=paramiko.Transport(sock);t.banner_timeout=30;t.auth_timeout=30;t.start_client(timeout=30)
    fp=hostkey_sha256(t.get_remote_server_key())
    expected=env["AKERPASS_SFTP_HOSTKEY_SHA256"]
    if fp!=expected:
        t.close()
        raise RuntimeError(f"SFTP HOST KEY MISMATCH: expected {expected}, got {fp}")
    t.auth_password(username=user,password=password)
    return t,paramiko.SFTPClient.from_transport(t)

def read_remote(sftp,path)->bytes:
    with sftp.open(path,"rb") as f: return f.read()

def ensure_dir(sftp,path:str)->None:
    path=path.rstrip("/")
    if not path: return
    parts=path.split("/")
    cur="/" if path.startswith("/") else ""
    for part in parts:
        if not part: continue
        cur=posixpath.join(cur,part) if cur else part
        try: sftp.stat(cur)
        except IOError: sftp.mkdir(cur)

def rm_tree(sftp,path:str)->None:
    try:
        attrs=sftp.listdir_attr(path)
    except IOError:
        return
    import stat
    for a in attrs:
        child=posixpath.join(path,a.filename)
        if stat.S_ISDIR(a.st_mode):
            rm_tree(sftp,child)
        else:
            sftp.remove(child)
    sftp.rmdir(path)

def upload_member(sftp,zf:zipfile.ZipFile,info:zipfile.ZipInfo,remote_path:str)->None:
    ensure_dir(sftp,posixpath.dirname(remote_path))
    with zf.open(info,"r") as src, sftp.open(remote_path,"wb") as dst:
        for chunk in iter(lambda:src.read(1024*1024),b""):
            dst.write(chunk)
    st=sftp.stat(remote_path)
    if int(st.st_size)!=int(info.file_size):
        raise RuntimeError(f"Remote size mismatch after upload: {info.filename}")

def http_get(url:str,user:str,password:str)->tuple[int,bytes]:
    token=base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    req=urllib.request.Request(
        url,
        headers={
            "Authorization":"Basic "+token,
            "Cache-Control":"no-cache",
            "Pragma":"no-cache",
            "User-Agent":"AkerPass-U5-RC1-Smoke/1.0",
        },
    )
    with urllib.request.urlopen(req,timeout=45) as r:
        return int(r.status),r.read()

def hosted_smoke(env:dict[str,str],cache_bust:str)->dict:
    base=env["AKERPASS_PREVIEW_URL"].rstrip("/")+"/"
    user=env["AKERPASS_PREVIEW_HTTP_USER"]
    password=b64d(env["AKERPASS_PREVIEW_HTTP_PASSWORD_B64"])
    out={}

    status,body=http_get(base+"?u5="+cache_bust,user,password)
    text=body.decode("utf-8",errors="replace")
    required=[
        "AKERPASS_UNIFIED_WEB_V0A",
        "AKERFRO_ROTATION_V1A_PRIORITY_UI",
        "AKERVATTEN_VISS_UI_V0A",
        'href="rapskartan25/"',
    ]
    missing=[x for x in required if x not in text]
    if status!=200 or missing:
        raise RuntimeError(f"Hosted root smoke failed: HTTP {status}, missing={missing}")
    out["root"]={"status":status,"bytes":len(body),"markers":"PASS"}

    status,body=http_get(base+"data/akerfro/rotation_v1a_priority_override.json?u5="+cache_bust,user,password)
    d=json.loads(body.decode("utf-8-sig"))
    if (
        int(d.get("rotation_release_fields",0))!=43
        or int(d.get("bestmatch_v0c_fields",0))!=37
        or int(d.get("d0_area_lt_1ha_fields",0))!=6
        or int((d.get("fields") or {}).get("61723351559|2B",{}).get("rank") or -1)!=273
        or int((d.get("fields") or {}).get("61723351559|2A",{}).get("rank") or -1)!=1436
    ):
        raise RuntimeError("Hosted Rotation v1.1 priority override anchors failed")
    out["rotation_priority_ui"]={"status":status,"anchors":"43=37+6; 2B#273; 2A#1436"}

    status,body=http_get(base+"data/akerfro_bestmatch/skane_index.json?u5="+cache_bust,user,password)
    d=json.loads(body.decode("utf-8-sig"))
    if d.get("status")!="FROZEN_BESTMATCH_V0C_PRESENTATION" or int(d.get("candidate_fields",0))!=16004 or int(d.get("field_union_count",0))!=5000:
        raise RuntimeError("Hosted BestMatch v0c anchors failed")
    out["bestmatch_v0c"]={"status":status,"candidates":16004,"screening_union":5000}

    status,body=http_get(base+"data/akervatten/skane_index.json?u5="+cache_bust,user,password)
    d=json.loads(body.decode("utf-8-sig"))
    if int(d.get("field_count",0))!=128636:
        raise RuntimeError("Hosted ÅkerVatten field anchor failed")
    out["akervatten"]={"status":status,"fields":128636}

    status,body=http_get(base+"rapskartan25/index.html?u5="+cache_bust,user,password)
    text=body.decode("utf-8",errors="replace")
    if status!=200 or "AKERPASS_RAPSKARTAN_BACKLINK_V0A" not in text:
        raise RuntimeError("Hosted Rapskartan smoke failed")
    out["rapskartan25"]={"status":status,"backlink":"PASS"}
    return out

def main()->int:
    env=read_env()
    required=[
        "AKERPASS_SFTP_HOST","AKERPASS_SFTP_PORT","AKERPASS_SFTP_USER",
        "AKERPASS_SFTP_PASSWORD_B64","AKERPASS_SFTP_HOSTKEY_SHA256",
        "AKERPASS_PREVIEW_REMOTE_ROOT","AKERPASS_PREVIEW_REMOTE_ROOT_CONFIRMED",
        "AKERPASS_PREVIEW_URL","AKERPASS_PREVIEW_HTTP_USER","AKERPASS_PREVIEW_HTTP_PASSWORD_B64",
    ]
    missing=[k for k in required if not env.get(k)]
    if missing:
        raise RuntimeError("Missing U5 .env settings: "+", ".join(missing))
    if env["AKERPASS_PREVIEW_REMOTE_ROOT_CONFIRMED"]!="YES":
        raise RuntimeError("Preview remote root is not explicitly confirmed.")
    if env["AKERPASS_PREVIEW_URL"].rstrip("/")!="https://preview.akerpass.se":
        raise RuntimeError("Wrong preview URL guard.")

    m=json.loads(RC_MANIFEST.read_text(encoding="utf-8-sig"))
    if m.get("release_name")!=EXPECTED_RELEASE:
        raise RuntimeError("Wrong RC release manifest.")
    zp=Path(m["package"]["path"])
    if not zp.is_file(): raise FileNotFoundError(zp)
    zsha=sha256_file(zp)
    if zsha!=EXPECTED_ZIP_SHA or zsha!=m["package"]["sha256"]:
        raise RuntimeError(f"RC1 ZIP SHA mismatch: {zsha}")

    root=env["AKERPASS_PREVIEW_REMOTE_ROOT"].rstrip("/") or "/"
    if root in ("/",".","/httpd.www","httpd.www"):
        raise RuntimeError(f"Refusing dangerous/main-domain remote root: {root}")

    print("="*118)
    print("ÅkerPass Unified Preview · U5 ONE.COM DEPLOY RC1")
    print("="*118)
    print("RC:",EXPECTED_RELEASE)
    print("ZIP SHA256:",zsha)
    print("Remote preview root:",root)
    print("Target URL: https://preview.akerpass.se/")
    print()

    t,sftp=connect(env)
    backup=None
    committed_top=[]
    auth_before={}
    try:
        resolved=sftp.normalize(root)
        if resolved!=root:
            print("SFTP normalized root:",resolved)
            root=resolved

        names=set(sftp.listdir(root))
        if not PROTECTED.issubset(names):
            raise RuntimeError("HARD GUARD FAILED: preview root must already contain both .htaccess and .htpasswd")
        auth_before={x:read_remote(sftp,posixpath.join(root,x)) for x in PROTECTED}
        ht=auth_before[".htaccess"].decode("utf-8",errors="replace")
        if sum(x.lower() in ht.lower() for x in ("AuthType","AuthUserFile","Require valid-user"))<2:
            raise RuntimeError("HARD GUARD FAILED: .htaccess no longer looks like preview Basic Auth")
        if "index.html" in names:
            idx=read_remote(sftp,posixpath.join(root,"index.html"))[:2_000_000].decode("utf-8",errors="replace")
            if "ÅkerPass" not in idx and "AkerPass" not in idx and "AKERPASS" not in idx:
                raise RuntimeError("HARD GUARD FAILED: current remote index is not ÅkerPass")

        short=zsha[:12]
        stage=posixpath.join(root,f".__akerpass_stage_{short}")
        stamp=dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup=posixpath.join(root,f".__akerpass_backup_before_{short}_{stamp}")

        print("[1/5] Stage exact RC1 behind deny-all guard...")
        rm_tree(sftp,stage)
        ensure_dir(sftp,stage)
        with sftp.open(posixpath.join(stage,".htaccess"),"wb") as f:
            f.write(DENY_ALL)

        with zipfile.ZipFile(zp,"r") as zf:
            infos=[i for i in zf.infolist() if not i.is_dir()]
            if len(infos)!=189:
                raise RuntimeError(f"RC ZIP member count drift: {len(infos)} != 189")
            root_names={i.filename.split("/",1)[0] for i in infos}
            if PROTECTED.intersection(root_names):
                raise RuntimeError("RC ZIP unexpectedly contains root auth files; refusing deploy")
            total=sum(i.file_size for i in infos)
            done=0
            for n,info in enumerate(infos,1):
                rp=posixpath.join(stage,info.filename)
                upload_member(sftp,zf,info,rp)
                done+=info.file_size
                if n%10==0 or n==len(infos):
                    print(f"  uploaded {n:>3}/{len(infos)} files · {100.0*done/max(1,total):5.1f}%")
        # Stage guard is not part of the release tree.
        sftp.remove(posixpath.join(stage,".htaccess"))
        print("  stage upload: PASS")

        print("[2/5] Move current preview into protected rollback folder...")
        ensure_dir(sftp,backup)
        with sftp.open(posixpath.join(backup,".htaccess"),"wb") as f:
            f.write(DENY_ALL)

        keep={stage.split("/")[-1],backup.split("/")[-1],*PROTECTED}
        existing=sftp.listdir(root)
        old_items=[x for x in existing if x not in keep and not x.startswith(".__akerpass_backup_")]
        for name in old_items:
            sftp.rename(posixpath.join(root,name),posixpath.join(backup,name))
        print(f"  previous top-level items backed up: {len(old_items)}")

        print("[3/5] Commit staged RC1 to preview root...")
        stage_items=sftp.listdir(stage)
        for name in stage_items:
            if name in PROTECTED:
                raise RuntimeError(f"Protected name unexpectedly present in stage: {name}")
            src=posixpath.join(stage,name);dst=posixpath.join(root,name)
            sftp.rename(src,dst)
            committed_top.append(name)
        sftp.rmdir(stage)

        # Auth files must remain byte-identical.
        for name,before in auth_before.items():
            after=read_remote(sftp,posixpath.join(root,name))
            if sha256_bytes(after)!=sha256_bytes(before):
                raise RuntimeError(f"Protected auth file changed during deploy: {name}")
        print(f"  committed top-level RC items: {len(committed_top)}")
        print("  .htaccess/.htpasswd preserved byte-for-byte")

        print("[4/5] Hosted HTTPS smoke through Basic Auth...")
        smoke=hosted_smoke(env,short)
        for k,v in smoke.items():
            print(" ",k,":",v)
        print("  hosted smoke: PASS")

        print("[5/5] Write local deploy receipt; keep remote rollback snapshot until U6...")
        RECEIPT_DIR.mkdir(parents=True,exist_ok=True)
        receipt={
            "schema_version":"akerpass-u5-onecom-deploy-receipt-v1",
            "status":"DEPLOYED_HOSTED_SMOKE_PASS_MOBILE_SMOKE_PENDING",
            "deployed_at_local":dt.datetime.now().astimezone().isoformat(),
            "release_name":EXPECTED_RELEASE,
            "zip_sha256":zsha,
            "preview_url":"https://preview.akerpass.se/",
            "remote_root":root,
            "remote_rollback_dir":backup,
            "auth_files_preserved_sha256":{k:sha256_bytes(v) for k,v in auth_before.items()},
            "hosted_smoke":smoke,
            "u5_mobile_smoke_pending":[
                "VISS layer on real phone",
                "field drawer/touch layout",
                "Min position permission + GPS",
                "Följ mig ON/OFF while moving",
                "pan/zoom while follow is active",
                "municipality/layer switching",
                "Rapskartan navigation/backlink",
            ],
        }
        RECEIPT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("="*118)
        print("AKERPASS U5 DEPLOY: HOSTED MACHINE SMOKE PASS")
        print("="*118)
        print("Preview: https://preview.akerpass.se/")
        print("Remote rollback snapshot retained until U6:",backup)
        print("Receipt:",RECEIPT)
        print("Next: real-phone HTTPS mobile/GPS smoke. Do NOT delete rollback snapshot yet.")
        print("="*118)
        return 0

    except Exception:
        # Automatic rollback only if we have already committed new top-level items.
        if backup and committed_top:
            print()
            print("DEPLOY/SMOKE FAILURE AFTER COMMIT — AUTOMATIC ROLLBACK STARTED")
            try:
                for name in committed_top:
                    p=posixpath.join(root,name)
                    try:
                        st=sftp.stat(p)
                        import stat
                        if stat.S_ISDIR(st.st_mode): rm_tree(sftp,p)
                        else: sftp.remove(p)
                    except Exception:
                        pass
                # Restore prior content except backup deny file.
                for name in sftp.listdir(backup):
                    if name==".htaccess": continue
                    sftp.rename(posixpath.join(backup,name),posixpath.join(root,name))
                rm_tree(sftp,backup)
                for name,before in auth_before.items():
                    after=read_remote(sftp,posixpath.join(root,name))
                    if sha256_bytes(after)!=sha256_bytes(before):
                        print("WARNING: auth-file hash mismatch after rollback:",name)
                print("AUTOMATIC ROLLBACK: COMPLETE")
            except Exception as rb:
                print("AUTOMATIC ROLLBACK FAILED:",type(rb).__name__,rb)
                print("Manual recovery may be required using remote backup:",backup)
        raise
    finally:
        try: sftp.close()
        except Exception: pass
        t.close()

if __name__=="__main__":
    raise SystemExit(main())
