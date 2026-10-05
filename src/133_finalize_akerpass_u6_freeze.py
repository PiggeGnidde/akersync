#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize ÅkerPass Unified Preview U6 web freeze.

This script performs no rebuild and no new deployment. It:
1) re-runs hosted HTTPS verification,
2) validates SFTP host/root and Basic-Auth files against the U5 receipt,
3) validates the exact U5 rollback directory,
4) removes only that guarded rollback snapshot,
5) re-runs hosted verification,
6) writes the final freeze manifest for the exact RC1 artifact.

The real-phone/Tesla mobile smoke was ACKed by the user before this tool was
created; that ACK is recorded as a freeze input, not re-inferred here.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import posixpath
import socket
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import paramiko

ROOT=Path(__file__).resolve().parents[1]
ENV_PATH=ROOT/".env"
U5_RECEIPT=ROOT/"work"/"akerpass_u5_deploy"/"u5_deploy_receipt.json"
RC_MANIFEST=ROOT/"work"/"akerpass_unified_rc1"/"akerpass_unified_preview_v0a_r1_rc1_manifest.json"
FINAL_DIR=ROOT/"work"/"akerpass_u6_freeze"
FINAL_MANIFEST=FINAL_DIR/"akerpass_unified_preview_v0a_r1_final_manifest.json"
FINAL_RELEASE_COPY=ROOT/"release"/"akerpass_unified_preview_v0a_r1_FINAL.json"

EXPECTED_RELEASE="akerpass-unified-preview-v0a-r1-rc1"
FINAL_RELEASE="akerpass-unified-preview-v0a-r1-final"
EXPECTED_ZIP_SHA="01a96dda7ced90be99a686f8de081ed72fc19f0fd4b1adf556d42de7def48173"
EXPECTED_ROLLBACK_PREFIX=".__akerpass_backup_before_01a96dda7ced_"
PROTECTED=(".htaccess",".htpasswd")
DENY_ALL=b"Require all denied\n"

def load_json(path:Path)->dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_env()->dict[str,str]:
    if not ENV_PATH.is_file():
        raise FileNotFoundError(".env missing")
    out={}
    for raw in ENV_PATH.read_text(encoding="utf-8",errors="replace").splitlines():
        s=raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k,v=s.split("=",1)
        out[k.strip()]=v.strip()
    return out

def b64d(s:str)->str:
    return base64.b64decode(s.encode("ascii")).decode("utf-8")

def sha256_bytes(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def hostkey_sha256(key:paramiko.PKey)->str:
    d=hashlib.sha256(key.asbytes()).digest()
    return "SHA256:"+base64.b64encode(d).decode("ascii").rstrip("=")

def connect(env:dict[str,str]):
    host=env["AKERPASS_SFTP_HOST"]
    port=int(env.get("AKERPASS_SFTP_PORT","22"))
    user=env["AKERPASS_SFTP_USER"]
    password=b64d(env["AKERPASS_SFTP_PASSWORD_B64"])

    sock=socket.create_connection((host,port),timeout=30)
    t=paramiko.Transport(sock)
    t.banner_timeout=30
    t.auth_timeout=30
    t.start_client(timeout=30)

    fp=hostkey_sha256(t.get_remote_server_key())
    expected=env["AKERPASS_SFTP_HOSTKEY_SHA256"]
    if fp!=expected:
        t.close()
        raise RuntimeError(f"SFTP HOST KEY MISMATCH: expected {expected}, got {fp}")
    t.auth_password(username=user,password=password)
    return t,paramiko.SFTPClient.from_transport(t),fp

def read_remote(sftp:paramiko.SFTPClient,path:str)->bytes:
    with sftp.open(path,"rb") as f:
        return f.read()

def rm_tree(sftp:paramiko.SFTPClient,path:str)->None:
    attrs=sftp.listdir_attr(path)
    for a in attrs:
        child=posixpath.join(path,a.filename)
        if stat.S_ISDIR(a.st_mode):
            rm_tree(sftp,child)
        else:
            sftp.remove(child)
    sftp.rmdir(path)

def run_hosted_verify(label:str)->None:
    print(label)
    r=subprocess.run(
        [sys.executable,str(ROOT/"src"/"132_verify_akerpass_u5_hosted.py")],
        cwd=ROOT,
    )
    if r.returncode!=0:
        raise RuntimeError(f"Hosted HTTPS verifier failed ({label})")

def zip_root_names(zp:Path)->set[str]:
    with zipfile.ZipFile(zp,"r") as zf:
        infos=[i for i in zf.infolist() if not i.is_dir()]
        if len(infos)!=189:
            raise RuntimeError(f"RC ZIP member count drift: {len(infos)} != 189")
        return {i.filename.split("/",1)[0] for i in infos}

def stable_json(x)->str:
    return json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+"\n"

def main()->int:
    env=read_env()
    u5=load_json(U5_RECEIPT)
    rc=load_json(RC_MANIFEST)

    if u5.get("status")!="DEPLOYED_HOSTED_SMOKE_PASS_MOBILE_SMOKE_PENDING":
        raise RuntimeError("Unexpected U5 receipt status")
    if u5.get("release_name")!=EXPECTED_RELEASE:
        raise RuntimeError("U5 receipt release mismatch")
    if u5.get("zip_sha256")!=EXPECTED_ZIP_SHA:
        raise RuntimeError("U5 receipt ZIP SHA mismatch")
    if rc.get("release_name")!=EXPECTED_RELEASE:
        raise RuntimeError("RC manifest release mismatch")
    if rc.get("package",{}).get("sha256")!=EXPECTED_ZIP_SHA:
        raise RuntimeError("RC manifest ZIP SHA mismatch")

    zp=Path(rc["package"]["path"])
    if not zp.is_file():
        raise FileNotFoundError(zp)
    if sha256_file(zp)!=EXPECTED_ZIP_SHA:
        raise RuntimeError("Local RC1 ZIP bytes no longer match frozen SHA")

    root=env["AKERPASS_PREVIEW_REMOTE_ROOT"].rstrip("/")
    receipt_root=str(u5.get("remote_root") or "").rstrip("/")
    if root!=receipt_root:
        raise RuntimeError(f"Remote root drift: .env={root}, U5 receipt={receipt_root}")
    if env.get("AKERPASS_PREVIEW_URL","").rstrip("/")!="https://preview.akerpass.se":
        raise RuntimeError("Preview URL guard failed")

    rollback=str(u5.get("remote_rollback_dir") or "").rstrip("/")
    if not rollback:
        raise RuntimeError("U5 receipt has no rollback directory")
    if posixpath.dirname(rollback)!=root:
        raise RuntimeError("Rollback directory is not directly under the confirmed preview root")
    rb_name=posixpath.basename(rollback)
    if not rb_name.startswith(EXPECTED_ROLLBACK_PREFIX):
        raise RuntimeError(f"Rollback guard failed for {rb_name}")

    print("="*118)
    print("ÅkerPass Unified Preview · U6 FINAL WEB FREEZE")
    print("="*118)
    print("Live release:",EXPECTED_RELEASE)
    print("RC1 SHA256:",EXPECTED_ZIP_SHA)
    print("Preview:",env["AKERPASS_PREVIEW_URL"])
    print("Mobile smoke ACK: real phone + Tesla browser; GPS / Följ mig / zoom across layers")
    print()

    run_hosted_verify("[1/6] Hosted HTTPS verify before finalization...")

    print("[2/6] Re-validate pinned SFTP target and auth files...")
    t,sftp,fp=connect(env)
    try:
        normalized=sftp.normalize(root)
        if normalized!=root:
            raise RuntimeError(f"Remote root normalization drift: {normalized} != {root}")

        names=set(sftp.listdir(root))
        if not set(PROTECTED).issubset(names):
            raise RuntimeError("Protected auth files missing from live preview")

        expected_auth=u5.get("auth_files_preserved_sha256") or {}
        auth_after={}
        for name in PROTECTED:
            b=read_remote(sftp,posixpath.join(root,name))
            h=sha256_bytes(b)
            auth_after[name]=h
            if h!=expected_auth.get(name):
                raise RuntimeError(f"Auth file hash drift since U5: {name}")

        # Confirm all expected RC top-level items are live.
        roots=zip_root_names(zp)
        missing=sorted(x for x in roots if x not in names)
        if missing:
            raise RuntimeError("Live preview missing RC top-level items: "+", ".join(missing))

        print("  pinned host key: PASS")
        print("  exact preview root: PASS")
        print("  .htaccess/.htpasswd unchanged since U5: PASS")
        print("  RC1 top-level live tree present: PASS")

        print("[3/6] Validate exact guarded rollback snapshot...")
        try:
            rb_names=set(sftp.listdir(rollback))
        except IOError as e:
            raise RuntimeError(f"Expected U5 rollback snapshot is missing: {rollback}") from e
        if ".htaccess" not in rb_names:
            raise RuntimeError("Rollback snapshot has no deny-all .htaccess")
        rb_ht=read_remote(sftp,posixpath.join(rollback,".htaccess"))
        if rb_ht!=DENY_ALL:
            raise RuntimeError("Rollback .htaccess is not the exact U5 deny-all guard")
        print("  rollback guard: PASS")
        print("  rollback path:",rollback)

        print("[4/6] Remove only the exact U5 rollback snapshot...")
        rm_tree(sftp,rollback)
        try:
            sftp.stat(rollback)
            raise RuntimeError("Rollback directory still exists after cleanup")
        except IOError:
            pass
        print("  rollback removed: PASS")

    finally:
        try:sftp.close()
        except Exception:pass
        t.close()

    run_hosted_verify("[5/6] Hosted HTTPS verify after rollback cleanup...")

    print("[6/6] Write final freeze manifest...")
    now=dt.datetime.now().astimezone().isoformat()
    final={
        "schema_version":"akerpass-unified-preview-v0a-r1-final-freeze-v1",
        "release_name":FINAL_RELEASE,
        "status":"FINAL_WEB_FREEZE_PASS",
        "frozen_at_local":now,
        "hosted_url":"https://preview.akerpass.se/",
        "source_rc":{
            "release_name":EXPECTED_RELEASE,
            "zip_path":str(zp),
            "zip_sha256":EXPECTED_ZIP_SHA,
            "files":int(rc["dist"]["files"]),
            "dist_tree_sha256":rc["dist"]["tree_sha256"],
        },
        "upstream_freezes":{
            "akerfro_rotation_v1a":"FORMALLY_FROZEN",
            "akerfro_bestmatch_v0c":"FORMALLY_FROZEN",
        },
        "anchors":rc.get("anchors"),
        "u5_machine_smoke":{
            "receipt":str(U5_RECEIPT),
            "status":"PASS",
            "hosted_smoke":u5.get("hosted_smoke"),
        },
        "u5_manual_mobile_smoke":{
            "status":"ACK_PASS",
            "ack_source":"user explicit ACK after real-world drive test",
            "tested_clients":[
                "real mobile browser",
                "Tesla in-car web browser",
            ],
            "tested_functions":[
                "GPS / Min position",
                "Följ mig",
                "zoom",
                "all map layers",
            ],
            "result":"User reported that all tested functions worked well.",
        },
        "hosting_guards":{
            "sftp_host_key_sha256":fp,
            "remote_root":root,
            "auth_files_sha256":u5.get("auth_files_preserved_sha256"),
            "auth_files_unchanged_through_u6":True,
        },
        "rollback":{
            "u5_snapshot_path":rollback,
            "removed_during_u6":True,
            "reason":"U5 machine smoke and real-phone/Tesla mobile smoke both passed.",
        },
        "deployment":{
            "new_deployment_during_u6":False,
            "live_bytes":"exact frozen RC1 artifact deployed during U5",
        },
        "freeze_rule":"Any future hosted web-byte change requires a new release/version; do not mutate this freeze in place.",
    }
    FINAL_DIR.mkdir(parents=True,exist_ok=True)
    FINAL_MANIFEST.write_text(stable_json(final),encoding="utf-8")
    FINAL_RELEASE_COPY.parent.mkdir(parents=True,exist_ok=True)
    FINAL_RELEASE_COPY.write_text(stable_json(final),encoding="utf-8")

    print("="*118)
    print("AKERPASS UNIFIED PREVIEW U6: FINAL WEB FREEZE PASS")
    print("="*118)
    print("Final release:",FINAL_RELEASE)
    print("Frozen RC1 SHA256:",EXPECTED_ZIP_SHA)
    print("Hosted URL: https://preview.akerpass.se/")
    print("Rollback snapshot: REMOVED")
    print("Final manifest:",FINAL_MANIFEST)
    print("Release manifest copy:",FINAL_RELEASE_COPY)
    print("="*118)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
