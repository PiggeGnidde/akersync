# ÅkerVatten MVP v0a · STOPPUNKT E FREEZE

**Status: PASS**

STOPPUNKT E is frozen after the initial candidate validation and the focused E2 review.

E freezes the **candidate raw-feature set and directional semantics** for the five separate ÅkerVatten components. It does not freeze any 0–100 score or combined ÅkerVatten index.

## 1. MarkTorka · frozen primary candidates

Primary raw features:

- `sand_mean` — higher = more drought-prone.
- `twi_mean` — lower = more drought-prone.

No slope/relief feature is included in v0a because the E2 schema audit found no such column in the current soil, hydrology or D-field feature tables.

Slope/relief may be added in a later version after a deterministic source and full-population coverage are established.

## 2. MarkVäta · frozen primary candidates

Primary raw features:

- `clay_mean` — higher = more wetness-prone.
- `twi_mean` — higher = more wetness-prone.

MarkVäta is not defined as the inverse of MarkTorka.

The exact -1 directional correlation between `MarkTorka/low_twi` and `MarkVäta/high_twi` is expected because they deliberately reuse the same TWI raw feature with opposite directional interpretation.

## 3. GrundvattenTillgång · frozen primary candidate

Primary raw feature:

- `sgu_smallmag_value` — higher = greater modelled groundwater availability.

This is screening information and is not individual-well yield.

## 4. GrundvattenTorka · frozen primary candidates

Primary raw features:

- `gw_small_situation_le10_max_run_days` — higher = more persistent historically low groundwater situation.
- `gw_small_situation_summer_p10` — lower = more severe low groundwater situation during May-September.

These two features use the same SGU historical reference concept: `grundvattensituation`, which is relative to the corresponding time of year.

Diagnostic-only groundwater features retained outside the primary v0a component:

- `gw_small_situation_le20_max_run_days`
- `gw_small_fill_summer_p10`
- `gw_small_fill_le10_max_run_days`

### Why fyllnadsgrad is not primary in v0a

E/E2 showed that the oriented relationship between persistent low `grundvattensituation` and low summer `fyllnadsgrad` depends strongly on the unit's seasonal amplitude.

For the four seasonal-amplitude quartiles, the oriented correlations were approximately:

- Q1 low seasonality: -0.477
- Q2: -0.385
- Q3: +0.009
- Q4 high seasonality: +0.508

This supports treating `fyllnadsgrad` as complementary seasonal/storage context rather than mixing it directly into the primary GrundvattenTorka v0a component.

The longest low-situation episodes also showed coherent major drought-year structure, with the most common start years:

- 2025: 420 units
- 2018: 220 units
- 1976: 100 units

This is retained as a physical sanity check, not as a fitted calibration target.

## 5. YtvattenTorka · frozen primary candidates

Primary raw features:

- `sw_MLQ_MQ_ratio_total` — lower = more low-flow-prone relative to mean flow.
- `sw_MLQ_total_lps_km2_upstream` — lower = lower specific low flow.

Diagnostic-only surface-water candidates:

- `sw_MLQ_MQ_ratio_natural`
- `sw_MLQ_natural_lps_km2_upstream`

E found strong rank correlation between the two primary total-flow metrics (rho ≈ 0.924), but only about 0.647 overlap in their directional top 10%, so they are retained as complementary primary descriptors rather than collapsed to one raw variable.

The natural-flow counterparts are strongly redundant with the corresponding total-flow measures and remain diagnostics.

## Coverage frozen at E

Required primary candidate coverage:

- sand_mean: 96.702%
- twi_mean: 99.970%
- sgu_smallmag_value: 99.997%
- GrundvattenTorka primary history features: 100%
- YtvattenTorka primary history features: 100%

The lower soil coverage is inherited from the existing soil feature product and must remain visible as a data-quality flag in later component scoring.

## Weighting distinction

Historical groundwater and surface-water candidate distributions were reviewed both:

- unit-weighted;
- field-weighted.

This distinction remains part of the provenance/QA contract. Product field scores may be field-level, but hydrological feature selection must not be justified only from field-weighted statistics when many fields share the same hydrological unit.

## Guardrails

STOPPUNKT E freezes:

- which v0a raw features are primary vs diagnostic;
- the physical direction of each primary feature.

STOPPUNKT E does **not** freeze:

- percentile transforms;
- component weights;
- missing-data policy for component scores;
- any 0–100 component score;
- any combined ÅkerVatten score.

Physical/hydrological screening is not an assessment of legal withdrawal rights.

## Next checkpoint

STOPPUNKT F will create transparent candidate 0–100 transforms for the five separate components, with explicit missing-data handling and no combined index.
