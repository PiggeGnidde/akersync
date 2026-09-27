# ÅkerVatten MVP v0a · STOPPUNKT D historical raw features

STOPPUNKT D starts feature engineering from the B/C-frozen hydrological linkage. It does **not** freeze a combined ÅkerVatten score.

## Groundwater history

For each unique SGU-HYPE `omrade_id` used by the 128,636 Skåne fields, the official history URL is downloaded once and cached separately.

The expected SGU columns are:

- `datum`
- `omrade_id`
- `grundvattensituation_sma`
- `grundvattensituation_stora`
- `fyllnadsgrad_sma`
- `fyllnadsgrad_stora`

The first three areas are validated before the bulk acquisition. A history must span at least 50 years; this also detects an accidentally truncated OGC response before hundreds of downloads are attempted.

Raw groundwater features include:

- history coverage;
- median/P10 values;
- May-September median/P10;
- annual minimum distributions;
- May-September annual minimum distributions;
- fraction of days <=10 and <=20;
- low-state persistence: maximum consecutive run and annual run-duration distributions.

These are descriptive historical inputs, not a drought score.

## Surface-water history

D uses SMHI Vattenwebb's official `Flödesstatistik` workbook and the frozen C mapping:

    ARO_UUID <-> Aroid -> Subid

The workbook's multi-row header is parsed explicitly. D extracts the documented MQ and MLQ series for total, stations-corrected and natural flow where available.

Derived raw features include:

- MLQ/MQ ratio;
- MQ and MLQ in m³/s;
- specific MQ/MLQ in l/s/km² using SVAR `AREA_UPSTREAM`, explicitly converting the source area from m² to km²;
- total/natural MLQ ratio where available.

The documented flow-statistics reference period is 1981-2010.

## Resumability

SGU-HYPE:
- each area is its own cached CSV;
- progress is printed every 25 areas;
- each successful source file survives interruption.

Groundwater features:
- Parquet checkpoint every 25 areas.

Field join:
- Parquet checkpoint every 5,000 fields;
- exact field identity is verified before a checkpoint is reused.

Thus a restart uses already completed downloads and joins.

## Optional D2 preparation

D also writes the 502 frozen S-HYPE SUBIDs into conservative batches of at most 50:

    work/akervatten_mvp_v0a/d_history/nadia_d2_batches/

These can later be used in the documented NADIA UI for daily flow histories from 1991 onward. Batch size 50 is an engineering choice, not an SMHI-published limit.

D1 does not require these manual downloads; they are prepared for a later daily-series augmentation if needed.

## Main outputs

    work/akervatten_mvp_v0a/d_history/
      groundwater_history_features.parquet
      surfacewater_history_features.parquet
      akervatten_d_history_features_skane.parquet
      d_summary.json
      sgu_feature_checkpoints/
      field_checkpoints/
      nadia_d2_batches/

Raw SGU history cache:

    data/raw/akervatten/d_history/sgu_hype_history/

No legal water-withdrawal right is inferred from these data.
