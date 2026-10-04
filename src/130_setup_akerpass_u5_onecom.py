#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive one-time U5 SFTP setup for preview.akerpass.se.

Secrets are stored only in local .env (already gitignored). No deploy occurs.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import os
import posixpath
import socket
from pathlib import Path

import paramiko

ROOT=Path(__file__).resolve().parents[1]
ENV_PATH=ROOT/".env"

KEYS=[
    "AKERPASS_SFTP_HOST",
    "AKERPASS_SFTP_PORT",
    "AKERPASS_SFTP_USER",
    "AKERPASS_SFTP_PASSWORD_B64",
    "AKERPASS_SFTP_HOSTKEY_SHA256",
    "AKERPASS_PREVIEW_REMOTE_ROOT",
    "AKERPASS_PREVIEW_REMOTE_ROOT_CONFIRMED",
    "AKERPASS_PREVIEW_URL",
    "AKERPASS_PREVIEW_HTTP_USER",
    "AKERPASS_PREVIEW_HTTP_PASSWORD_B64",
]

def read_env()->dict[str,str]:
    out={}
    if not ENV_PATH.is_file():
        return out
    for raw in ENV_PATH.read_text(encoding="utf-8",errors="replace").splitlines():
        s=raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k,v=s.split("=",1)
        out[k.strip()]=v.strip()
    return out

def update_env(values:dict[str,str])->None:
    lines=[]
    seen=set()
    if ENV_PATH.is_file():
        for raw in ENV_PATH.read_text(encoding="utf-8",errors="replace").splitlines():
            s=raw.strip()
            if s and not s.startswith("#") and "=" in s:
                k=s.split("=",1)[0].strip()
                if k in values:
                    lines.append(f"{k}={values[k]}")
                    seen.add(k)
                    continue
            lines.append(raw)
    if lines and lines[-1]!="":
        lines.append("")
    lines.append("# ÅkerPass U5 one.com SFTP deploy")
    for k in KEYS:
        if k in values and k not in seen:
            lines.append(f"{k}={values[k]}")
            seen.add(k)
    ENV_PATH.write_text("\n".join(lines).rstrip()+"\n",encoding="utf-8")

def b64e(s:str)->str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")

def b64d(s:str)->str:
    try:
        return base64.b64decode(s.encode("ascii")).decode("utf-8")
    except Exception:
        return ""

def hostkey_sha256(key:paramiko.PKey)->str:
    d=hashlib.sha256(key.asbytes()).digest()
    return "SHA256:"+base64.b64encode(d).decode("ascii").rstrip("=")

def connect_transport(host:str,port:int,user:str,password:str,expected_fp:str|None):
    sock=socket.create_connection((host,port),timeout=20)
    t=paramiko.Transport(sock)
    t.banner_timeout=20
    t.auth_timeout=20
    t.start_client(timeout=20)
    key=t.get_remote_server_key()
    fp=hostkey_sha256(key)
    print(f"Server host key: {key.get_name()} {fp}")
    if expected_fp and fp!=expected_fp:
        t.close()
        raise RuntimeError(
            f"SFTP host key changed: expected {expected_fp}, got {fp}. "
            "Refusing connection."
        )
    t.auth_password(username=user,password=password)
    return t,fp

def candidate_roots(raw:str)->list[str]:
    raw=raw.strip().replace("\\","/")
    out=[]
    def add(x):
        if x and x not in out: out.append(x)
    add(raw)
    add("/"+raw.lstrip("/"))
    if raw.startswith("/webroots/"):
        tail=raw[len("/webroots/"):].strip("/")
        add("/"+tail); add(tail)
    elif raw.startswith("webroots/"):
        tail=raw[len("webroots/"):].strip("/")
        add("/"+tail); add(tail)
    if raw.startswith("/httpd.www/"):
        add(raw[len("/httpd.www"):])
    return out

def resolve_root(sftp:paramiko.SFTPClient,raw:str)->str:
    errors=[]
    for c in candidate_roots(raw):
        try:
            sftp.stat(c)
            return sftp.normalize(c)
        except Exception as e:
            errors.append(f"{c}: {type(e).__name__}")
    raise FileNotFoundError("Could not resolve preview root. Tried: "+", ".join(errors))

def read_remote_bytes(sftp:paramiko.SFTPClient,path:str,limit:int=2_000_000)->bytes:
    with sftp.open(path,"rb") as f:
        return f.read(limit)

def prompt(label:str,default:str="")->str:
    suffix=f" [{default}]" if default else ""
    x=input(label+suffix+": ").strip()
    return x or default

def main()->int:
    env=read_env()
    print("="*112)
    print("ÅkerPass U5 · one.com SFTP SETUP")
    print("="*112)
    print("No deployment is performed by this setup.")
    print()
    print("Use the connection details shown in one.com Control Panel → SSH & SFTP.")
    print("For the preview root, use the Folder shown for subdomain preview under Subdomains.")
    print("On newer one.com servers this may look like /webroots/<hash>.")
    print()

    host=prompt("SFTP host",env.get("AKERPASS_SFTP_HOST",""))
    port=int(prompt("SFTP port",env.get("AKERPASS_SFTP_PORT","22")))
    user=prompt("SFTP username",env.get("AKERPASS_SFTP_USER",""))
    oldpw=b64d(env.get("AKERPASS_SFTP_PASSWORD_B64",""))
    password=getpass.getpass("SFTP password"+(" [Enter keeps existing]: " if oldpw else ": "))
    if not password and oldpw: password=oldpw
    if not all([host,user,password]):
        raise RuntimeError("Host, username and password are required.")

    expected=env.get("AKERPASS_SFTP_HOSTKEY_SHA256") or None
    t,fp=connect_transport(host,port,user,password,expected)
    try:
        if not expected:
            ans=input("First connection. Type YES to trust and pin this exact host key: ").strip()
            if ans!="YES":
                raise RuntimeError("Host key was not approved.")
        sftp=paramiko.SFTPClient.from_transport(t)
        rawroot=prompt("Preview remote root / Folder",env.get("AKERPASS_PREVIEW_REMOTE_ROOT",""))
        if not rawroot:
            raise RuntimeError("Preview remote root is required.")
        root=resolve_root(sftp,rawroot)
        print("Resolved remote root:",root)

        names=set(sftp.listdir(root))
        print("Remote root contains:",", ".join(sorted(names)[:40]))
        for protected in (".htaccess",".htpasswd"):
            if protected not in names:
                raise RuntimeError(
                    f"Guard failed: {protected} is missing from {root}. "
                    "This deploy flow requires the already password-protected preview root."
                )

        htaccess=read_remote_bytes(sftp,posixpath.join(root,".htaccess")).decode("utf-8",errors="replace")
        auth_score=sum(x.lower() in htaccess.lower() for x in ("AuthType","AuthUserFile","Require valid-user"))
        if auth_score<2:
            raise RuntimeError(
                "Guard failed: preview .htaccess does not look like the existing Basic Auth protection."
            )
        if len(read_remote_bytes(sftp,posixpath.join(root,".htpasswd"),limit=1_000_000))<3:
            raise RuntimeError("Guard failed: preview .htpasswd is empty.")

        if "index.html" in names:
            idx=read_remote_bytes(sftp,posixpath.join(root,"index.html")).decode("utf-8",errors="replace")
            if "ÅkerPass" not in idx and "AkerPass" not in idx and "AKERPASS" not in idx:
                raise RuntimeError("Guard failed: existing preview index.html does not look like ÅkerPass.")

        print()
        print("HARD GUARD PASSED: target is password-protected and looks like the existing ÅkerPass preview.")
        print("Resolved root:",root)
        ans=input("Type PREVIEW to bind future U5 deploys to this exact remote root: ").strip()
        if ans!="PREVIEW":
            raise RuntimeError("Preview root not confirmed.")

        preview_url=prompt("Preview URL",env.get("AKERPASS_PREVIEW_URL","https://preview.akerpass.se/"))
        if preview_url.rstrip("/")!="https://preview.akerpass.se":
            raise RuntimeError("U5 is hard-bound to https://preview.akerpass.se/")

        http_user=prompt("Preview HTTP Basic Auth username",env.get("AKERPASS_PREVIEW_HTTP_USER",""))
        oldhpw=b64d(env.get("AKERPASS_PREVIEW_HTTP_PASSWORD_B64",""))
        http_password=getpass.getpass("Preview HTTP Basic Auth password"+(" [Enter keeps existing]: " if oldhpw else ": "))
        if not http_password and oldhpw: http_password=oldhpw
        if not http_user or not http_password:
            raise RuntimeError("Preview HTTP Basic Auth credentials are required for hosted smoke verification.")

        values={
            "AKERPASS_SFTP_HOST":host,
            "AKERPASS_SFTP_PORT":str(port),
            "AKERPASS_SFTP_USER":user,
            "AKERPASS_SFTP_PASSWORD_B64":b64e(password),
            "AKERPASS_SFTP_HOSTKEY_SHA256":fp,
            "AKERPASS_PREVIEW_REMOTE_ROOT":root,
            "AKERPASS_PREVIEW_REMOTE_ROOT_CONFIRMED":"YES",
            "AKERPASS_PREVIEW_URL":"https://preview.akerpass.se/",
            "AKERPASS_PREVIEW_HTTP_USER":http_user,
            "AKERPASS_PREVIEW_HTTP_PASSWORD_B64":b64e(http_password),
        }
        update_env(values)
        print()
        print("="*112)
        print("AKERPASS U5 SFTP SETUP: PASS")
        print("="*112)
        print("Saved locally in .env. No secrets were written to Git.")
        print("Remote preview root:",root)
        print("Host key pinned:",fp)
        print("Deployment performed: NO")
        print("="*112)
        return 0
    finally:
        t.close()

if __name__=="__main__":
    raise SystemExit(main())
