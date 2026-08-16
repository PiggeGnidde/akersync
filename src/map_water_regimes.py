#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build an exploratory Skåne map of four water regimes from existing features.

Input is the robust eligible population created by explore_water_prospects.py.
The map is deliberately descriptive, not an agronomic diagnosis.

Axes (all percentile-based within the robust Skåne population):
  texture_axis = clay_percentile - sand_percentile
      > 0 => relatively clayey, < 0 => relatively sandy
  wetness_axis = 2 * wetness_percentile - 1
      > 0 => relatively wet topographic position, < 0 => relatively dry

Four regimes:
  1 CLAY_WET  : relatively clayey + relatively wet (drainage-challenge side)
  2 SAND_DRY  : relatively sandy + relatively dry (irrigation-sensitivity side)
  3 SAND_WET  : relatively sandy + relatively wet (topography offsets sandiness)
  4 CLAY_DRY  : relatively clayey + relatively dry (soil retention / dry topography)

A regime-strength measure 0..100 is also computed from distance from both median
splits. Borderline fields therefore get pale colours on the overview map instead
of looking as certain as strong quadrant examples.
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_bounds

from common import load_config


REGIMES = {
    1: {
        "code": "CLAY_WET",
        "label": "Relativt lerig + topografiskt våt",
        "short": "Lera + vått",
        "interpretation": "Dräneringsutmaning / vattenöverskottssida",
        "rgb": (78, 70, 153),
    },
    2: {
        "code": "SAND_DRY",
        "label": "Relativt sandig + topografiskt torr",
        "short": "Sand + torrt",
        "interpretation": "Bevattningskänslighet / vattenunderskottssida",
        "rgb": (224, 123, 57),
    },
    3: {
        "code": "SAND_WET",
        "label": "Relativt sandig + topografiskt våt",
        "short": "Sand + vått",
        "interpretation": "Lätt jord där topografin samlar vatten",
        "rgb": (55, 148, 151),
    },
    4: {
        "code": "CLAY_DRY",
        "label": "Relativt lerig + topografiskt torr",
        "short": "Lera + torrt",
        "interpretation": "Vattenhållande jord i torrare topografiskt läge",
        "rgb": (162, 119, 76),
    },
}


def classify(z: pd.DataFrame) -> pd.DataFrame:
    x = z.copy()
    needed = ["clay_pctile", "sand_pctile", "wetness_pctile"]
    missing = [c for c in needed if c not in x.columns]
    if missing:
        raise RuntimeError(
            "water_prospect_features_skiften.csv saknar kolumner: " + ", ".join(missing)
        )

    x["texture_axis"] = (
        pd.to_numeric(x["clay_pctile"], errors="coerce")
        - pd.to_numeric(x["sand_pctile"], errors="coerce")
    )
    x["wetness_axis"] = 2.0 * pd.to_numeric(x["wetness_pctile"], errors="coerce") - 1.0

    clayey = x["texture_axis"] >= 0
    wet = x["wetness_axis"] >= 0
    x["water_regime_id"] = np.select(
        [clayey & wet, (~clayey) & (~wet), (~clayey) & wet, clayey & (~wet)],
        [1, 2, 3, 4],
        default=0,
    ).astype(int)

    # Distance from the two median split lines. Both terms are in [0,1].
    # Geometric mean means a field close to either split is shown as weak/borderline.
    a = np.clip(np.abs(x["texture_axis"]), 0.0, 1.0)
    b = np.clip(np.abs(x["wetness_axis"]), 0.0, 1.0)
    x["water_regime_strength"] = 100.0 * np.sqrt(a * b)

    x["water_regime"] = x["water_regime_id"].map(
        {k: v["code"] for k, v in REGIMES.items()}
    )
    x["water_regime_label"] = x["water_regime_id"].map(
        {k: v["label"] for k, v in REGIMES.items()}
    )
    return x


def normalize_keys(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["blockid"] = x["blockid"].astype(str)
    x["skiftesbeteckning"] = x["skiftesbeteckning"].astype(str)
    return x


def make_summary(x: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rid, meta in REGIMES.items():
        q = x[x.water_regime_id == rid]
        rows.append({
            "water_regime_id": rid,
            "water_regime": meta["code"],
            "label": meta["label"],
            "interpretation": meta["interpretation"],
            "skiften": int(len(q)),
            "area_ha": float(pd.to_numeric(q.area_ha, errors="coerce").sum()),
            "median_clay_pct": float(pd.to_numeric(q.clay_mean, errors="coerce").median()),
            "median_sand_pct": float(pd.to_numeric(q.sand_mean, errors="coerce").median()),
            "median_twi": float(pd.to_numeric(q.twi_mean, errors="coerce").median()),
            "median_strength": float(pd.to_numeric(q.water_regime_strength, errors="coerce").median()),
        })
    return pd.DataFrame(rows)


def top_municipalities(x: pd.DataFrame, n=5) -> pd.DataFrame:
    rows = []
    for rid, meta in REGIMES.items():
        q = x[x.water_regime_id == rid].copy()
        if "kommun" not in q.columns:
            continue
        g = (
            q.groupby("kommun", dropna=False)
            .agg(skiften=("blockid", "size"), area_ha=("area_ha", "sum"))
            .sort_values(["area_ha", "skiften"], ascending=False)
            .head(n)
            .reset_index()
        )
        for rank, r in enumerate(g.itertuples(index=False), 1):
            rows.append({
                "water_regime": meta["code"],
                "rank": rank,
                "kommun": str(r.kommun),
                "skiften": int(r.skiften),
                "area_ha": float(r.area_ha),
            })
    return pd.DataFrame(rows)


def render_map(all_skiften: gpd.GeoDataFrame, eligible: gpd.GeoDataFrame, out_png: Path, width=1800):
    # Use all 2025 skiften as a light-grey farmland silhouette, then colour the robust subset.
    minx, miny, maxx, maxy = all_skiften.total_bounds
    dx, dy = maxx - minx, maxy - miny
    pad = 0.015 * max(dx, dy)
    left, bottom, right, top = minx-pad, miny-pad, maxx+pad, maxy+pad
    aspect = (top-bottom) / (right-left)
    height = max(900, int(round(width * aspect)))
    transform = from_bounds(left, bottom, right, top, width, height)

    base_shapes = ((g, 1) for g in all_skiften.geometry if g is not None and not g.is_empty)
    base = rasterize(
        base_shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )

    class_shapes = (
        (g, int(rid))
        for g, rid in zip(eligible.geometry, eligible.water_regime_id)
        if g is not None and not g.is_empty and int(rid) in REGIMES
    )
    classes = rasterize(
        class_shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )

    strength_shapes = (
        (g, float(s))
        for g, s in zip(eligible.geometry, eligible.water_regime_strength)
        if g is not None and not g.is_empty and np.isfinite(s)
    )
    strength = rasterize(
        strength_shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        dtype="float32",
        all_touched=True,
    )

    # White background; farmland outside robust eligible set is pale grey.
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    img[base == 1] = np.array([225, 225, 225], dtype=np.uint8)

    for rid, meta in REGIMES.items():
        m = classes == rid
        if not np.any(m):
            continue
        # Borderline fields remain pale; strong quadrant examples carry the full colour.
        alpha = 0.30 + 0.70 * np.clip(strength[m] / 100.0, 0.0, 1.0)
        rgb = np.array(meta["rgb"], dtype=np.float32)
        white = np.array([245, 245, 245], dtype=np.float32)
        blended = white[None, :] * (1.0-alpha[:, None]) + rgb[None, :] * alpha[:, None]
        img[m] = np.clip(blended, 0, 255).astype(np.uint8)

    Image.fromarray(img, mode="RGB").save(out_png, format="PNG", optimize=True)
    return width, height


def swatch(rgb):
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def build_html(summary: pd.DataFrame, topmun: pd.DataFrame, out_html: Path, png_name: str, n_eligible: int):
    legend = "".join(
        f'<div class="legend-item"><span class="swatch" style="background:{swatch(meta["rgb"])}"></span>'
        f'<div><b>{html.escape(meta["short"])}</b><br><span>{html.escape(meta["interpretation"])}</span></div></div>'
        for _, meta in REGIMES.items()
    )

    srows = []
    for r in summary.itertuples(index=False):
        meta = REGIMES[int(r.water_regime_id)]
        srows.append(
            "<tr>"
            f'<td><span class="mini" style="background:{swatch(meta["rgb"])}"></span>{html.escape(meta["short"])}</td>'
            f"<td>{r.skiften:,}</td><td>{r.area_ha:,.0f}</td>"
            f"<td>{r.median_clay_pct:.1f}</td><td>{r.median_sand_pct:.1f}</td>"
            f"<td>{r.median_twi:.2f}</td><td>{r.median_strength:.1f}</td>"
            "</tr>"
        )
    summary_rows = "".join(srows)

    cards = []
    for rid, meta in REGIMES.items():
        q = topmun[topmun.water_regime == meta["code"]]
        items = "".join(
            f"<li>{html.escape(str(r.kommun))}: {r.area_ha:,.0f} ha ({r.skiften:,} skiften)</li>"
            for r in q.itertuples(index=False)
        ) or "<li>–</li>"
        cards.append(
            f'<div class="card"><h3><span class="mini" style="background:{swatch(meta["rgb"])}"></span>{html.escape(meta["short"])}</h3>'
            f"<ol>{items}</ol></div>"
        )

    text = f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerSync · Skånes vattenregimer</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;margin:0;background:#f5f5f2;color:#222}}
main{{max-width:1500px;margin:auto;padding:28px}}
h1{{margin-bottom:4px}} .sub{{color:#555;margin-top:0;max-width:1000px}}
.panel{{background:white;border:1px solid #ddd;border-radius:12px;padding:18px;margin:18px 0;box-shadow:0 1px 4px #0001}}
.map{{width:100%;height:auto;display:block;border:1px solid #ddd;background:white}}
.legend{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:14px 0}}
.legend-item{{display:flex;gap:10px;align-items:center;padding:8px;border-radius:8px;background:#fafafa}}
.swatch{{width:28px;height:28px;border-radius:5px;display:inline-block;flex:none}}
.mini{{width:13px;height:13px;border-radius:3px;display:inline-block;margin-right:7px;vertical-align:-1px}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:right}} th:first-child,td:first-child{{text-align:left}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}} .card{{background:#fafafa;border:1px solid #ddd;border-radius:10px;padding:12px}} .card h3{{margin-top:0}}
.note{{font-size:.94rem;color:#555}} code{{background:#eee;padding:2px 4px;border-radius:4px}}
</style>
</head>
<body><main>
<h1>ÅkerSync · Skånes vattenregimer</h1>
<p class="sub">Explorativ fyrfältskarta för {n_eligible:,} robusta 2025-skiften. Jordaxeln bygger på relativa ler-/sandpercentiler och vattenaxeln på topografisk TWI-percentil. Detta är en proxykarta, inte observerad dränering eller bevattningsstatus.</p>
<div class="panel">
<img class="map" src="{html.escape(png_name)}" alt="Skånes vattenregimer">
<div class="legend">{legend}</div>
<p class="note">Grått = 2025-skifte som inte ingår i robusthetsurvalet. Färgstyrkan visar hur tydligt skiftet ligger från båda medianlinjerna; blek färg betyder gränsfall.</p>
</div>
<div class="panel">
<h2>Sammanfattning</h2>
<table><thead><tr><th>Regim</th><th>Skiften</th><th>Area ha</th><th>Median lera %</th><th>Median sand %</th><th>Median TWI</th><th>Median styrka</th></tr></thead><tbody>{summary_rows}</tbody></table>
</div>
<div class="panel"><h2>Kommuner med störst klassad areal</h2><div class="cards">{''.join(cards)}</div></div>
<div class="panel">
<h2>Metod</h2>
<p><code>texture_axis = percentile(lera) - percentile(sand)</code>. Positivt värde klassas som relativt lerigt, negativt som relativt sandigt.</p>
<p><code>wetness_axis = 2 × percentile(TWImean) - 1</code>. Positivt värde ligger över medianen för topografisk våthetsbenägenhet, negativt under medianen.</p>
<p><code>strength = 100 × sqrt(|texture_axis| × |wetness_axis|)</code>. Måttet påverkar bara kartans färgstyrka, inte vilken av de fyra regimerna ett skifte tillhör.</p>
<p class="note">Jorddata = modellerad DSMS2025-textur. TWI = topografisk våthetsbenägenhet från ÅkerSync-hydrologin. Dikning, bevattningsanläggningar, grundvatten, nederbörd, gröda och faktisk markfukt ingår inte i denna klassning.</p>
</div>
</main></body></html>"""
    out_html.write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/local_paths.json")
    ap.add_argument("--width", type=int, default=1800, help="PNG-bredd i pixlar")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / args.config)
    d = root / cfg.get("build_dir", "data/derived")
    dist = root / cfg.get("dist_dir", "dist")
    dist.mkdir(parents=True, exist_ok=True)

    source = d / "water_prospect_features_skiften.csv"
    if not source.exists():
        raise RuntimeError(
            f"Saknas: {source}\nKör EXPLORE_WATER_PROSPECTS.bat först."
        )

    z = pd.read_csv(
        source,
        dtype={"blockid": str, "skiftesbeteckning": str, "kommun": str},
    )
    z = classify(normalize_keys(z))
    if (z.water_regime_id == 0).any():
        raise RuntimeError("Några robusta skiften kunde inte klassificeras i de fyra regimerna")

    skiften = gpd.read_file(cfg["skiften"])
    if skiften.crs is None:
        raise RuntimeError("Skiftefilen saknar CRS")
    skiften = skiften.to_crs(3006)
    skiften = normalize_keys(skiften)

    cols = ["blockid", "skiftesbeteckning", "water_regime_id", "water_regime_strength"]
    g = skiften.merge(z[cols], on=["blockid", "skiftesbeteckning"], how="inner", validate="one_to_one")
    if len(g) != len(z):
        raise RuntimeError(f"Geometrimatchning misslyckades: features={len(z):,}, geometri={len(g):,}")

    summary = make_summary(z)
    topmun = top_municipalities(z)

    out_features = d / "water_regimes_skiften.csv"
    out_summary = d / "water_regimes_summary.csv"
    out_mun = d / "water_regimes_top_municipalities.csv"
    out_png = dist / "water_regimes_skane.png"
    out_html = dist / "water_regimes_skane.html"

    z.to_csv(out_features, index=False, encoding="utf-8-sig")
    summary.to_csv(out_summary, index=False, encoding="utf-8-sig")
    topmun.to_csv(out_mun, index=False, encoding="utf-8-sig")

    print("Rasteriserar Skånekartan ...")
    w, h = render_map(skiften, g, out_png, width=args.width)
    build_html(summary, topmun, out_html, out_png.name, len(z))

    print("=" * 96)
    print("ÅkerSync · vattenregimer · KLART")
    print("=" * 96)
    print(f"Robusta skiften klassade: {len(z):,}")
    for r in summary.itertuples(index=False):
        meta = REGIMES[int(r.water_regime_id)]
        print(f"  {meta['short']:14s}: {r.skiften:6,d} skiften  {r.area_ha:10,.0f} ha  median TWI={r.median_twi:6.2f}")
    print(f"Karta:   {out_png} ({w}×{h}px)")
    print(f"HTML:    {out_html}")
    print(f"Features:{out_features}")
    print(f"Summary: {out_summary}")
    print("\nOBS: explorativ proxyklassning — inte observerad dränerings-/bevattningsstatus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
