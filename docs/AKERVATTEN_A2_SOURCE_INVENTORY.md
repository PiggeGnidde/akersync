# ÅkerVatten MVP v0a · STOPPUNKT A2 official source inventory

A2 implements the original handoff STOPPUNKT A after the local A1/A1b reuse audits.

## Scope

Probe only official current routes for:

- SGU Grundvattentillgång i små magasin
- SGU Grundvattenmagasin
- SGU-HYPE areas and historical daily data
- SMHI SVAR2022 geometry
- SMHI S-HYPE / Vattenwebb / NADIA
- SGU and SMHI license terms

No full public raster, vector package or long time series is downloaded.

## SGU small aquifers

A2 checks both:

- packaged ZIP route
- WCS GetCapabilities

The bulk ZIP is touched only with HEAD or a 0-byte range-style probe.

Expected semantics remain:

- 100 x 100 m raster
- l/day/ha
- screening/planning only
- not an individual-well yield claim

## SGU-HYPE

A2 verifies:

- collections `omraden` and `grundvattennivaer-tidigare`
- queryable schemas
- one area feature
- `omrade_id`
- `url_tidsserie`
- a five-row filtered historical sample
- CRS/storage CRS
- license link

This proves a documented cacheable area-ID -> historical-series route without downloading full histories.

## SMHI

A2 verifies:

- official SVAR2022 WFS capabilities
- official SVAR2022 packaged-download route without downloading the package
- Vattenwebb model-data documentation
- NADIA bulk-download page and documented SUBID/AROID input
- current modelarea service page
- SMHI open-data license page

### Important open question for STOPPUNKT B

Do not assume the public SVAR2022 polygon attributes directly equal the current S-HYPE identifiers used by NADIA.

A2 records this as:

`OPEN_FOR_STOPPUNKT_B`

The deterministic 100-field pilot must prove a documented geometry -> current SUBID/AROID linkage before full-Skåne spatial linkage.

This is deliberate. The project rules say not to reverse-engineer undocumented service endpoints merely to force an automated join.

## Outputs

    work\akervatten_mvp_v0a\a2_source_inventory\source_inventory.json
    work\akervatten_mvp_v0a\a2_source_inventory\source_inventory.md

## PASS

PASS means the official products, access routes, schemas and licenses needed to start the tiny pilot are reachable and understood.

It does not mean:

- that legal water-withdrawal rights have been assessed;
- that public regional groundwater data represent a property-specific well;
- that SVAR2022/current S-HYPE identifier linkage has already been proven;
- that any ÅkerVatten score has been frozen.
