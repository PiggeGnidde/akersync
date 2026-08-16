#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

ROOT = Path(__file__).resolve().parents[1]
GEOM = ROOT / "data/derived/geometry_v1a_skiften.csv"
TARGET = ROOT / "data/derived/geometry_crop_ranked_1to5ha.csv"
COEF = ROOT / "data/derived/geometry_orthogonal_coefficients.csv"
OUT_CSV = ROOT / "data/derived/geometry_o141_rectangularity_marginals.csv"
OUT_HTML = ROOT / "dist/geometry_o141_rectangularity_marginals.html"

MODEL_ID = "O141"
AREA_LEVELS = [1.0, 2.0, 3.0, 5.0]
MAIN = ["log_area", "rectangularity", "convexity", "compactness", "log_aspect", "has_holes"]
EXTRA = ["area2", "rect2", "conv2", "compact2", "rect_x_area"]
TERMS = MAIN + EXTRA


def normalise_text(x):
    return str(x).strip().lower().replace("å", "a").replace("ä", "a").replace("ö", "o")


def infer_target(df: pd.DataFrame):
    for c in ["is_active_cultivation", "active_cultivation", "is_crop", "cultivated"]:
        if c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            if set(s.dropna().unique()).issubset({0, 1}):
                return s, c
    for c in ["landuse_group", "land_use_group", "crop_group", "group"]:
        if c not in df.columns:
            continue
        out = []
        for v in df[c]:
            t = normalise_text(v)
            if any(k in t for k in ["odling", "special", "crop", "active", "aker"]):
                out.append(1.0)
            elif any(k in t for k in ["bete", "pasture", "skydd", "trada", "miljo", "meadow", "noncrop", "non-crop"]):
                out.append(0.0)
            else:
                out.append(np.nan)
        s = pd.Series(out, index=df.index, dtype=float)
        if s.notna().sum() > 1000:
            return s, c
    raise RuntimeError("Kunde inte hitta binärt mål i geometry_crop_ranked_1to5ha.csv")


def make_main_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["log_area"] = np.log(pd.to_numeric(df["area_ha"], errors="coerce"))
    f["rectangularity"] = pd.to_numeric(df["rectangularity"], errors="coerce")
    f["convexity"] = pd.to_numeric(df["convexity"], errors="coerce")
    f["compactness"] = pd.to_numeric(df["compactness_4piA_P2"], errors="coerce")
    f["log_aspect"] = np.log(pd.to_numeric(df["mbr_aspect_ratio"], errors="coerce"))
    f["has_holes"] = (pd.to_numeric(df["hole_count"], errors="coerce").fillna(0) > 0).astype(float)
    return f


def fit_scaling(raw: pd.DataFrame):
    z = pd.DataFrame(index=raw.index)
    scale = {}
    for c in MAIN:
        x = raw[c].astype(float)
        mu = float(x.mean())
        sd = float(x.std(ddof=0))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0
        scale[c] = (mu, sd)
        z[c] = (x - mu) / sd

    extra_raw = pd.DataFrame(index=raw.index)
    extra_raw["area2"] = z["log_area"] ** 2
    extra_raw["rect2"] = z["rectangularity"] ** 2
    extra_raw["conv2"] = z["convexity"] ** 2
    extra_raw["compact2"] = z["compactness"] ** 2
    extra_raw["rect_x_area"] = z["rectangularity"] * z["log_area"]
    for c in EXTRA:
        x = extra_raw[c].astype(float)
        mu = float(x.mean())
        sd = float(x.std(ddof=0))
        if not np.isfinite(sd) or sd < 1e-12:
            sd = 1.0
        scale[c] = (mu, sd)
        z[c] = (x - mu) / sd
    return z, scale


def apply_scaling(raw: pd.DataFrame, scale: dict) -> pd.DataFrame:
    z = pd.DataFrame(index=raw.index)
    for c in MAIN:
        mu, sd = scale[c]
        z[c] = (raw[c].astype(float) - mu) / sd
    extra_raw = pd.DataFrame(index=raw.index)
    extra_raw["area2"] = z["log_area"] ** 2
    extra_raw["rect2"] = z["rectangularity"] ** 2
    extra_raw["conv2"] = z["convexity"] ** 2
    extra_raw["compact2"] = z["compactness"] ** 2
    extra_raw["rect_x_area"] = z["rectangularity"] * z["log_area"]
    for c in EXTRA:
        mu, sd = scale[c]
        z[c] = (extra_raw[c] - mu) / sd
    return z


def predict(z: pd.DataFrame, beta: dict) -> np.ndarray:
    eta = np.full(len(z), float(beta["intercept"]), dtype=float)
    for t in TERMS:
        eta += z[t].to_numpy(float) * float(beta[t])
    return expit(np.clip(eta, -35, 35))


def svg_chart(curves: pd.DataFrame, rect_lo: float, rect_hi: float) -> str:
    W, H = 1000, 610
    L, R, T, B = 92, 38, 72, 78
    pw, ph = W - L - R, H - T - B
    def sx(x): return L + (x - rect_lo) / (rect_hi - rect_lo) * pw
    def sy(y): return T + (1 - y) * ph

    colors = {1.0:"#7f1d1d", 2.0:"#b45309", 3.0:"#2563eb", 5.0:"#15803d"}
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<text x="500" y="30" text-anchor="middle" font-family="Arial" font-size="22" font-weight="700">O141: rectangularity × fältstorlek</text>',
             '<text x="500" y="53" text-anchor="middle" font-family="Arial" font-size="13" fill="#555">Genomsnittlig modellprediktion för aktiv odling; övrig geometri behålls som observerad</text>']
    for y in np.arange(0, 1.01, 0.1):
        yy = sy(float(y))
        parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(f'<text x="{L-12}" y="{yy+4:.1f}" text-anchor="end" font-family="Arial" font-size="12">{int(y*100)}%</text>')
    for x in np.linspace(rect_lo, rect_hi, 6):
        xx = sx(float(x))
        parts.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{H-B}" stroke="#f3f4f6" stroke-width="1"/>')
        parts.append(f'<text x="{xx:.1f}" y="{H-B+24}" text-anchor="middle" font-family="Arial" font-size="12">{x:.2f}</text>')
    parts.append(f'<line x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}" stroke="#111" stroke-width="1.5"/>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H-B}" stroke="#111" stroke-width="1.5"/>')
    parts.append(f'<text x="{(L+W-R)/2:.1f}" y="{H-22}" text-anchor="middle" font-family="Arial" font-size="14">Rectangularity</text>')
    parts.append(f'<text x="22" y="{(T+H-B)/2:.1f}" text-anchor="middle" font-family="Arial" font-size="14" transform="rotate(-90 22 {(T+H-B)/2:.1f})">Predikterad sannolikhet aktiv odling</text>')

    for area in AREA_LEVELS:
        sub = curves[curves.area_ha == area].sort_values("rectangularity")
        pts = " ".join(f"{sx(r.rectangularity):.1f},{sy(r.predicted_active_probability):.1f}" for r in sub.itertuples())
        c = colors[area]
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')

    lx, ly = W-250, T+18
    parts.append(f'<rect x="{lx-18}" y="{ly-24}" width="205" height="126" rx="8" fill="white" stroke="#d1d5db"/>')
    for i, area in enumerate(AREA_LEVELS):
        yy = ly + i*26
        c = colors[area]
        parts.append(f'<line x1="{lx}" y1="{yy}" x2="{lx+34}" y2="{yy}" stroke="{c}" stroke-width="4"/>')
        parts.append(f'<text x="{lx+46}" y="{yy+4}" font-family="Arial" font-size="13">{area:g} ha</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def main():
    for p in [GEOM, TARGET, COEF]:
        if not p.exists():
            raise FileNotFoundError(f"Saknar {p}. Kör tidigare Geometry/contrast/orthogonal-steg först.")

    g = pd.read_csv(GEOM, dtype={"blockid": str, "skiftesbeteckning": str})
    t = pd.read_csv(TARGET, dtype={"blockid": str, "skiftesbeteckning": str})
    y0, target_source = infer_target(t)
    t = t[["blockid", "skiftesbeteckning"]].copy().assign(active_cultivation=y0)
    d = g.merge(t, on=["blockid", "skiftesbeteckning"], how="inner")
    d = d[d.active_cultivation.notna()].copy()
    d = d[(pd.to_numeric(d.area_ha, errors="coerce") >= 1.0) & (pd.to_numeric(d.area_ha, errors="coerce") <= 5.0)].copy()

    raw = make_main_features(d)
    mask = raw.notna().all(axis=1)
    d = d.loc[mask].reset_index(drop=True)
    raw = raw.loc[mask].reset_index(drop=True)
    _, scale = fit_scaling(raw)

    cf = pd.read_csv(COEF)
    cf = cf[cf.model_id.astype(str) == MODEL_ID].copy()
    beta = dict(zip(cf.term.astype(str), pd.to_numeric(cf.beta_std, errors="coerce")))
    missing = [x for x in ["intercept"] + TERMS if x not in beta or not np.isfinite(beta[x])]
    if missing:
        raise RuntimeError(f"O141-koefficienter saknas för: {missing}")

    # Average adjusted predictions: replace area + rectangularity for every observed row,
    # preserve each row's actual convexity/compactness/aspect/holes, then average p.
    rect_lo = max(0.02, float(raw.rectangularity.quantile(0.005)))
    rect_hi = min(0.995, float(raw.rectangularity.quantile(0.995)))
    rect_grid = np.linspace(rect_lo, rect_hi, 121)

    rows = []
    for area in AREA_LEVELS:
        for rect in rect_grid:
            cfraw = raw.copy()
            cfraw["log_area"] = math.log(area)
            cfraw["rectangularity"] = rect
            zcf = apply_scaling(cfraw, scale)
            p = predict(zcf, beta)
            rows.append({
                "area_ha": area,
                "rectangularity": rect,
                "predicted_active_probability": float(np.mean(p)),
                "population_n": len(p),
            })
    curves = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    curves.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    svg = svg_chart(curves, rect_lo, rect_hi)
    html = f'''<!doctype html><html lang="sv"><head><meta charset="utf-8"><title>O141 marginaleffekt</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;max-width:1100px}} .note{{color:#444;max-width:900px;line-height:1.45}} table{{border-collapse:collapse;margin-top:18px}}td,th{{border:1px solid #ddd;padding:6px 9px;text-align:right}}th:first-child,td:first-child{{text-align:left}}</style></head><body>
{svg}
<p class="note"><b>Tolkning:</b> Kurvorna är modellbaserade genomsnittliga prediktioner, inte kausala effekter. För varje punkt sätts area och rectangularity till det visade värdet för alla 49 497 skiften, medan varje skiftes observerade convexity, compactness, aspect och hål behålls. Sannolikheterna medelvärdesbildas sedan. Rectangularity-intervallet begränsas till ungefär observerad 0.5–99.5-percentil för att minska extrem extrapolation.</p>
<p class="note"><b>Target:</b> mänskligt markanvändningsbeslut 2025 ({target_source}), inte maskineffektivitet.</p>
</body></html>'''
    OUT_HTML.write_text(html, encoding="utf-8")

    print("="*96)
    print("ÅkerSync · O141 marginaleffekt: rectangularity × area")
    print("="*96)
    print(f"Population: {len(d):,} skiften | target: {target_source}")
    print(f"Rectangularity-grid: {rect_lo:.3f}–{rect_hi:.3f} (ca observerad 0.5–99.5-percentil)")
    print("Metod: average adjusted predictions; övrig geometri behålls observerad.")
    print()
    checkpoints = [0.10, 0.25, 0.50, 0.75, 0.90]
    print("Predikterad aktiv odling vid utvalda rectangularity-nivåer:")
    for area in AREA_LEVELS:
        vals = []
        sub = curves[curves.area_ha == area]
        for rr in checkpoints:
            ix = (sub.rectangularity - rr).abs().idxmin()
            row = sub.loc[ix]
            vals.append(f"R={row.rectangularity:.2f}: {100*row.predicted_active_probability:5.1f}%")
        print(f"  {area:g} ha  " + " | ".join(vals))
    print()
    print(f"CSV:  {OUT_CSV}")
    print(f"Graf: {OUT_HTML}")
    print("OBS: human revealed preference, inte kausalitet och inte maskinsimulering.")

if __name__ == "__main__":
    main()
