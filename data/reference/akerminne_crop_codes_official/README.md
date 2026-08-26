# ÅkerMinne official annual crop-code dictionaries 2015–2025

Official annual crop-code workbooks supplied by Jordbruksverket customer service on 2026-08-26 were normalized to one gzip-compressed CSV per year. The original Excel workbooks are not committed; exact source filenames and SHA-256 hashes are recorded in `manifest.json`.

## Contract

Each normalized CSV contains:

- `crop_code_raw`: annual `grdkod_mar` code.
- `crop_subcategory_raw`: annual `grdkod_und`/undercode when the supplied workbook contains an official undercode table; blank otherwise.
- `crop_name`: official crop/undercode label for that exact year.
- `crop_group`: intentionally blank in v1a; no inferred cross-year grouping.
- provenance columns: source page, receipt date, workbook sheet/row and whether the row came from the main or subcategory table.

ÅkerMinne must never borrow a code meaning from another year. Lookup order is:

1. exact `(year, crop_code_raw, crop_subcategory_raw)`;
2. the same year's main code `(year, crop_code_raw, blank)` if the exact undercode is absent;
3. otherwise the explicit `Okänd grödkod <kod> (<år>)` fallback.

Before use, `src/60_apply_akerminne_official_crop_codes.py` decompresses every annual file and checks its normalized SHA-256 and row count against `manifest.json`. The operation is label-only: geometry, intersections, coverage and identity matching are asserted unchanged.

## Source-format QA

- 2015: source filename ends in `.xls`, but the bytes are OOXML/Excel 2007+ ZIP content and were readable. Main sheet `Grödkoder 2015` is used; `Utvald miljö 2014` is excluded.
- 2016–2018: supplied workbooks contain a main crop-code sheet but no separate `Underkoder` sheet.
- 2019–2023: official `Underkoder` sheet uses alternating code/name column pairs.
- 2024–2025: official `Underkoder` sheet uses one parent-code column per crop family with combined undercode/name cells.
- 2022: workbook sheet name is `Grödkoder 2021`, but cell A1 states `Grödkodslista för SAM-ansökan 2022`; file year + in-sheet title therefore identify it as the 2022 list.

Hard QA anchors include `2015 / 4 = Vete (höst)` and `2019 / 74 / 119 = Matlök`, plus an explicit guard that the 2019 undercode meaning is never borrowed by 2018.
