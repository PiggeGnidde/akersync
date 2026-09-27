# ÅkerVatten MVP v0a · STOPPUNKT D FREEZE

**Status: PASS**

STOPPUNKT D is frozen as the historical raw-feature baseline after successful full-Skåne execution.

## Frozen population and historical coverage

- Field population: 128,636.
- SGU-HYPE units: 786 / 786 parsed.
- SGU-HYPE long-history validation: 786 / 786.
- S-HYPE/Vattenwebb units: 502 / 502 with MLQ.
- Fields with groundwater-history features: 128,636 / 128,636.
- Fields with surface-water MLQ features: 128,636 / 128,636.

Three initial SGU probes each returned 24,004 daily rows spanning 1961-01-01 through 2026-09-20 (65.7 years). All 786 unit histories subsequently passed the configured long-history QA.

## Frozen groundwater raw-feature family

Per unique SGU-HYPE omrade_id, D computes descriptive historical inputs from:

- grundvattensituation_sma
- grundvattensituation_stora
- fyllnadsgrad_sma
- fyllnadsgrad_stora

Feature families include:

- median and P10;
- May-September median and P10;
- annual minimum summaries;
- May-September annual minimum summaries;
- fraction of days <=10 and <=20;
- longest consecutive low-state runs;
- annual low-run duration summaries.

These are raw historical descriptors, not a frozen drought score.

## Frozen surface-water raw-feature family

Per unique S-HYPE Subid, D uses the official Vattenwebb flow-statistics baseline with MQ and MLQ for:

- total flow;
- station-corrected flow;
- natural flow.

Derived raw features include:

- MLQ/MQ ratio;
- MQ and MLQ in m³/s;
- specific MQ/MLQ in l/s/km² using upstream catchment area;
- total/natural MLQ ratio where defined.

The frozen flow-statistics reference period is 1981-2010.

## Full-population descriptive distributions

Field-weighted distributions from the frozen D run:

- gw_small_situation_le10_max_run_days:
  - P10 212
  - P50 235
  - P90 542
- gw_small_fill_summer_p10:
  - P10 5
  - P50 6
  - P90 9
- sw_MLQ_MQ_ratio_total:
  - P10 0.02633
  - P50 0.05833
  - P90 0.2393
- sw_MLQ_total_m3s:
  - P10 0.006768
  - P50 0.03171
  - P90 1.198
- sw_MLQ_total_lps_km2_upstream:
  - P10 0.09349
  - P50 0.5548
  - P90 2.382

These distributions are descriptive and field-weighted; they are not score thresholds.

## Resumability

The D pipeline is frozen as resumable:

- each SGU-HYPE area history cached independently;
- groundwater feature checkpoints every 25 areas;
- field joins checkpoint every 5,000 fields.

## D2 status

Full daily S-HYPE/NADIA histories from 1991 onward are **not required for STOPPUNKT D baseline PASS**.

The 502 Subids have been prepared in 11 batches of at most 50 IDs for an optional D2 daily-series augmentation. D2 may later add event-duration, seasonal low-flow, rolling-minimum and recent-vs-historical surface-water features.

## Guardrails

STOPPUNKT D freezes historical raw features only.

No MarkTorka, MarkVäta, GrundvattenTillgång, GrundvattenTorka, YtvattenTorka or combined ÅkerVatten score is frozen here.

SGU-HYPE and S-HYPE/Vattenwebb are modelled hydrological context. Physical/hydrological screening is not an assessment of legal withdrawal rights.

## Next checkpoint

Proceed to STOPPUNKT E: define and validate component-level risk transforms and/or empirical ranking behavior without yet collapsing everything into one opaque combined score.
