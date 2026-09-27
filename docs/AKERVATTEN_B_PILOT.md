# ÅkerVatten MVP v0a · STOPPUNKT B

This is the first real end-to-end data pilot after STOPPUNKT A.

## Deterministic 100 fields

The selection is deliberately not a random convenience sample.

For each municipality the selector attempts to include:

1. a relatively dry structural archetype: high sand + low TWI,
2. a relatively wet structural archetype: high clay + high TWI,
3. an A1b quality-edge field outside the old conservative robust subset.

The remainder is filled deterministically from stable field hashes, and at least one DATA_MISSING field is included when possible.

The same source population therefore gives the same pilot fields on every rerun.

## What B must prove

For the pilot, actual data — not only documentation — are connected end to end:

- current ÅkerPass field geometry;
- local soil and TWI;
- SGU Grundvattentillgång i små magasin raster values;
- SGU-HYPE area / omrade_id;
- several actual SGU-HYPE historical response files;
- SMHI SVAR2022 catchment polygons from the official bulk GeoPackage/ZIP (A2 WFS is retained as source-inventory evidence, but B uses bulk + local clipping for reproducibility);
- open Vattenwebb all-Sweden flow-statistics workbook;
- empirical proof of the SVAR polygon identifier -> current Vattenwebb SUBID/AROID mapping where the workbook supports it;
- a documented NADIA handoff with several mapped IDs for daily-series validation.

The separate SMHI realtime S-HYPE delivery is not used in the open-data MVP because direct file access requires authentication. B instead uses the documented Vattenwebb bulk flow-information download. Daily historical series remain available through the documented NADIA interface; B does not reverse-engineer NADIA's private backend endpoint.

## Why the coupling table matters

SMHI's official S-HYPE open-data README states that the product NetCDF uses an integer `id` and that the accompanying coupling table provides:

- SUBID,
- AROID,
- HARO.

B does not assume that an SVAR2022 attribute such as VAROID equals AROID. It tests candidate identifier pairs on the 100 spatially joined fields and requires >=95% empirical matching before accepting one.

## Strict B PASS

B requires:

- exactly 100 field identities retained;
- >=90% SGU small-magasin point coverage;
- >=95% SGU-HYPE area coverage;
- at least 3 actual SGU-HYPE historical series retrieved;
- >=95% SVAR2022 polygon coverage;
- >=95% mapping to S-HYPE SUBID;
- at least 3 mapped Vattenwebb basin IDs emitted for documented NADIA daily-series validation.

Until daily-series retrieval through the documented user-facing route is validated, B reports `PASS_WITH_WARNING`, not a full freeze PASS.

Any failure stops before full-Skåne scaling.

## Cached raw data

B caches downloaded public files under:

    data/raw/akervatten/b_pilot/

Large raw public files are not committed to Git.

Outputs go under:

    work/akervatten_mvp_v0a/b_pilot/

including:

- pilot_fields_100.gpkg
- pilot_fields_100_linked.parquet
- shype_current_flow_samples.parquet
- b_pilot_manifest.json

No MarkTorka, MarkVäta or combined score is frozen.

## SVAR2022 retrieval decision

STOPPUNKT A proved that SMHI's WFS capabilities are reachable, but a large Skåne GetFeature bbox returned a server-side HTTP 500 during the real pilot. B therefore uses SMHI's official packaged SVAR2022 download and clips locally in EPSG:3006. This is more reproducible and avoids making the pilot depend on a fragile server-side WFS bbox query.

## Access-control finding

The public-facing realtime S-HYPE product description states that realtime files are delivered as a web service against a delivery fee. Direct anonymous access to the coupling CSV returned HTTP 401 during the pilot. The project therefore does not attempt to bypass that control. The open Vattenwebb/NADIA products are used instead.


## 2026-09-27 correction: correct SVAR layer for S-HYPE

The first B implementation used `Vattenförekomstavrinningsområden_2022`.
That product is an aggregation around water bodies and is identified by `VAROID`.
It is not the correct direct key to S-HYPE model basins.

The correct hydrological geometry for the S-HYPE linkage is
`Delavrinningsområden_2022`. The official SVAR 2022:1.2 product
description defines `ARO_UUID` as the catchment identifier.

B therefore now fetches small official WFS windows around the 100 pilot
field points from `Delavrinningsomraden_2022` and accepts only the
semantic identifier contract:

    SVAR2022 Delavrinningsområden ARO_UUID
        <->
    Vattenwebb Aroid
        ->
    Vattenwebb Subid

No cross-column "best match" search is used for the acceptance decision.

The previously downloaded
`SVAR2022_Vattenforekomstavrinningsomraden.zip` is retained only as a
cached public artifact; it is no longer the B S-HYPE linkage source.
