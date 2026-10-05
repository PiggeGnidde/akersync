from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

try:
    import geopandas as gpd
except Exception:
    gpd = None

try:
    import pyarrow.parquet as pq
except Exception:
    pq = None

VERSION = "akerswap-c0-real-portfolio-audit-v0a"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "akerswap_c0_real_portfolio_audit_v0a"

SEARCH_ROOTS = [
    Path(r"C:\AkerSyncRaw"),
    Path(r"C:\AkerSync-Minne"),
    Path(r"C:\AkerSyncRepo\data"),
    Path(r"C:\AkerSync-AkerAccess"),
    Path(r"C:\AkerSync-AkerSwap"),
]

PREFERRED_FILES = [
    Path(r"C:\AkerSyncRaw\jv_skane_2025\arslager_skifte_skane_2025.gpkg"),
    Path(r"C:\AkerSyncRaw\jv_skane_2025\arslager_block_skane_2025.gpkg"),
]

POSITIVE_TOKENS = (
    "brukare", "bruknings", "brukningsenhet", "jordbrukare",
    "kund", "kundnr", "kundnummer",
    "ansokan", "ansok", "sam", "samansokan",
    "sokande", "foretag", "foretags", "enterprise",
    "operator", "producer", "producent",
    "holding", "farm", "farmer",
    "person", "personnr", "personnummer",
    "orgnr", "organisationsnummer", "organisation",
    "agare", "arrendator",
)

NEGATIVE_EXACT = {
    "blockid", "block_id", "skifte", "field_id", "field_key",
    "geometry", "geom", "region", "kommun", "lan",
    "groda", "crop", "year", "ar", "kod", "code", "area", "areal",
}


def norm(x):
    s = "" if x is None else str(x)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def token_score(col):
    n = norm(col)
    pos = sum(1 for t in POSITIVE_TOKENS if norm(t) in n)
    neg = 1 if n in NEGATIVE_EXACT else 0
    return pos * 10 - neg * 10


def schema(path):
    try:
        suf = path.suffix.lower()
        if suf == ".parquet" and pq is not None:
            return list(pq.ParquetFile(path).schema.names)
        if suf == ".csv":
            return list(pd.read_csv(path, nrows=0).columns)
        if suf == ".gpkg" and gpd is not None:
            try:
                import pyogrio
                info = pyogrio.read_info(path)
                return list(info.get("fields", []))
            except Exception:
                return list(gpd.read_file(path, rows=1).columns)
    except Exception:
        return []
    return []


def discover_files():
    files = []
    seen = set()

    for p in PREFERRED_FILES:
        if p.exists():
            files.append(p)
            seen.add(str(p).lower())

    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for ext in ("*.gpkg", "*.parquet", "*.csv"):
            for p in root.rglob(ext):
                sp = str(p).lower()
                if sp in seen:
                    continue
                n = norm(str(p))
                if not any(t in n for t in (
                    "skifte", "block", "field", "aker", "jordbruk",
                    "minne", "score", "drift", "arslager"
                )):
                    continue
                files.append(p)
                seen.add(sp)
                if len(files) >= 250:
                    return files
    return files


def read_candidate(path, cols):
    suf = path.suffix.lower()
    use = list(dict.fromkeys(cols))
    if suf == ".parquet":
        return pd.read_parquet(path, columns=use)
    if suf == ".csv":
        return pd.read_csv(path, usecols=lambda c: c in use, low_memory=False)
    if suf == ".gpkg":
        if gpd is None:
            return None
        try:
            return gpd.read_file(path, columns=use)
        except TypeError:
            d = gpd.read_file(path)
            return d[[c for c in use if c in d.columns]]
    return None


def usefulness(series):
    s = series.dropna()
    if len(s) == 0:
        return None

    vals = s.astype(str).str.strip()
    vals = vals[(vals != "") & (vals.str.lower() != "nan")]
    if len(vals) == 0:
        return None

    vc = vals.value_counts(dropna=True)
    nunique = len(vc)
    n = len(vals)
    repeat_fraction = float(vc[vc >= 2].sum() / n)
    groups_ge_3 = int((vc >= 3).sum())
    groups_ge_5 = int((vc >= 5).sum())
    groups_ge_10 = int((vc >= 10).sum())
    median_group = float(vc.median())
    p90_group = float(vc.quantile(0.90))
    max_group = int(vc.max())

    plausible = (
        nunique >= 5
        and nunique <= 0.80 * n
        and repeat_fraction >= 0.20
        and groups_ge_5 >= 5
        and max_group >= 5
    )

    return {
        "n_nonempty": n,
        "n_unique": nunique,
        "repeat_fraction": repeat_fraction,
        "groups_ge_3": groups_ge_3,
        "groups_ge_5": groups_ge_5,
        "groups_ge_10": groups_ge_10,
        "median_group_size": median_group,
        "p90_group_size": p90_group,
        "max_group_size": max_group,
        "plausible_grouping": bool(plausible),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("=" * 94)
    print("ÅkerSwap C0 - audit for real farm/operator portfolio identifiers")
    print("Version:", VERSION)
    print("=" * 94)

    files = discover_files()
    print(f"Candidate files discovered: {len(files)}")

    schema_rows = []
    candidate_rows = []

    for i, p in enumerate(files, 1):
        cols = schema(p)
        if not cols:
            schema_rows.append({
                "file": str(p), "status": "NO_SCHEMA", "n_cols": 0,
                "candidate_columns": "",
            })
            continue

        cand = []
        for c in cols:
            sc = token_score(c)
            if sc > 0:
                cand.append((c, sc))

        schema_rows.append({
            "file": str(p),
            "status": "OK",
            "n_cols": len(cols),
            "candidate_columns": " | ".join(f"{c}:{sc}" for c, sc in cand),
        })

        if not cand:
            continue

        print(f"[{i}/{len(files)}] {p}")
        print("  candidates:", ", ".join(c for c, _ in cand))

        try:
            d = read_candidate(p, [c for c, _ in cand])
            if d is None:
                continue
        except Exception as e:
            for c, sc in cand:
                candidate_rows.append({
                    "file": str(p), "column": c, "token_score": sc,
                    "status": "READ_ERROR_" + type(e).__name__,
                })
            continue

        for c, sc in cand:
            if c not in d.columns:
                continue
            u = usefulness(d[c])
            if u is None:
                candidate_rows.append({
                    "file": str(p), "column": c, "token_score": sc,
                    "status": "EMPTY",
                })
                continue

            candidate_rows.append({
                "file": str(p), "column": c, "token_score": sc,
                "status": "OK", **u,
            })

    inv = pd.DataFrame(schema_rows)
    cand = pd.DataFrame(candidate_rows)
    inv.to_csv(OUT / "schema_inventory.csv", index=False, encoding="utf-8-sig")
    cand.to_csv(OUT / "candidate_identifier_audit.csv", index=False, encoding="utf-8-sig")

    if not cand.empty and "plausible_grouping" in cand.columns:
        plausible = cand[
            (cand["status"] == "OK") & (cand["plausible_grouping"] == True)
        ].copy()
    else:
        plausible = pd.DataFrame()

    if plausible.empty:
        verdict = "NO_OPEN_PORTFOLIO_ID"
    else:
        plausible = plausible.sort_values(
            ["token_score", "groups_ge_5", "repeat_fraction"],
            ascending=[False, False, False],
        )
        verdict = "CANDIDATE_ID_FOUND"

    result = {
        "version": VERSION,
        "files_scanned": len(files),
        "candidate_columns_tested": int(len(cand)),
        "plausible_candidates": int(len(plausible)),
        "verdict": verdict,
    }
    (OUT / "verdict.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    md = [
        "# ÅkerSwap STOPPUNKT C0 - real portfolio identifier audit",
        "",
        f"Version: {VERSION}",
        f"Verdict: {verdict}",
        "",
        "## Syfte",
        "",
        "Före en riktig tvåbrukarstudie letar vi automatiskt igenom redan lokalt tillgängliga",
        "fält-/block-/Åker*-dataset efter stabila nycklar som kan representera brukare,",
        "SAM-ansökan, kund, företag, holding, producent eller liknande.",
        "",
        "Målet är att undvika manuell datainsamling om verkliga portföljer redan finns",
        "maskinläsbart i våra data.",
        "",
        "## Resultat",
        "",
        f"- filer inventerade: {len(files)}",
        f"- kandidatkolumner testade: {len(cand)}",
        f"- statistiskt plausibla gruppnycklar: {len(plausible)}",
        "",
    ]

    if verdict == "CANDIDATE_ID_FOUND":
        md += [
            "Minst en kolumn beter sig statistiskt som en möjlig portföljnyckel.",
            "Detta är inte ännu bevis att kolumnen verkligen betyder brukare/företag.",
            "Nästa steg är semantisk kontroll av de bästa kandidaterna innan någon ÅkerSwap-analys görs.",
            "",
            "Top candidates:",
            "",
        ]
        for _, r in plausible.head(10).iterrows():
            md.append(
                f"- {r['column']} i {r['file']}: "
                f"{int(r['n_unique'])} grupper, "
                f"{int(r['groups_ge_5'])} grupper med >=5 rader, "
                f"max {int(r['max_group_size'])} rader/grupp."
            )
    else:
        md += [
            "Ingen kolumn i de lokala maskinläsbara data beter sig både semantiskt och",
            "statistiskt som en användbar brukar-/portföljnyckel.",
            "",
            "## Rekommenderat nästa steg",
            "",
            "C1: minimal riktig tvåbrukarstudie.",
            "",
            "Varje deltagande lantbrukare behöver endast ange sina egna skiften",
            "(field_id eller välja dem i befintlig ÅkerPass-karta). Ingen ägar-/arrendedatabas byggs.",
            "Solvern kan sedan använda befintlig ÅkerScore/ÅkerDrift/geometri automatiskt.",
        ]

    (OUT / "STOPPUNKT_C0.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("")
    print("=" * 94)
    print("AKERSWAP_C0_RESULT")
    print("VERDICT=" + verdict)
    print(f"FILES_SCANNED={len(files)}")
    print(f"CANDIDATE_COLUMNS_TESTED={len(cand)}")
    print(f"PLAUSIBLE_CANDIDATES={len(plausible)}")
    if not plausible.empty:
        for k, (_, r) in enumerate(plausible.head(5).iterrows(), 1):
            print(
                f"TOP{k}={r['column']} | {r['file']} | "
                f"groups={int(r['n_unique'])} | ge5={int(r['groups_ge_5'])} | "
                f"max={int(r['max_group_size'])}"
            )
    print("OUT=" + str(OUT))
    print("=" * 94)


if __name__ == "__main__":
    main()
