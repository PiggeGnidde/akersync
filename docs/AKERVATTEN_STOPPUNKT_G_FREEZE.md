# ÅkerVatten MVP v0a · STOPPUNKT G FREEZE

**Status: PASS**

STOPPUNKT G is frozen after full-population sanity validation and focused G2 review.

G validates the five component scales frozen at STOPPUNKT F. It does not modify formulas, fit parameters or create a combined ÅkerVatten index.

## Population and score ranges

Field population: 128,636.

Frozen component output ranges:

- MarkTorka: n=124,380; min 0.07; P10 20.94; P50 51.22; P90 78.27; max 99.62.
- MarkVäta: n=124,380; min 0.00; P10 6.02; P50 34.96; P90 74.10; max 99.92.
- GrundvattenTillgång: n=128,632; min 0.00; P10 9.99; P50 49.99; P90 89.99; max 100.00.
- GrundvattenTorka: n=128,636; min 0.48; P10 27.29; P50 48.73; P90 80.73; max 96.21.
- YtvattenTorka: n=128,636; min 0.10; P10 12.48; P50 58.18; P90 90.42; max 98.70.

## Hydrological invariants

- GrundvattenTorka: 786 / 786 expected SGU-HYPE units; zero units with inconsistent field scores.
- YtvattenTorka: 502 / 502 expected S-HYPE units; zero units with inconsistent field scores.

## Raw-driver sanity check · top vs bottom 10%

### MarkTorka

Bottom 10% vs top 10%:

- sand_mean: 43.930 -> 69.000
- twi_mean: 10.047 -> 6.587

This is directionally consistent with the frozen MarkTorka definition.

### MarkVäta

Bottom 10% vs top 10%:

- twi_mean: 6.144 -> 9.905
- clay_mean: 5.100 -> 17.440
- organic_ge20_share_pct median: 0 -> 0

The organic median being zero in both deciles is not a contradiction. The organic branch is sparse/zero-inflated and was retained to capture a separate minority population; the dominant route into the top MarkVäta decile remains the mineral/topographic branch.

### GrundvattenTillgång

Bottom 10% vs top 10%:

- sgu_smallmag_value: 966 -> 2834

Direction is consistent with the frozen availability definition.

### GrundvattenTorka

Bottom 10% vs top 10%:

- gw_small_situation_le10_max_run_days: 188 -> 538
- gw_small_situation_summer_p10: 9 -> 8

Direction is consistent with the frozen groundwater-drought definition.

### YtvattenTorka

Bottom 10% vs top 10%:

- sw_MLQ_MQ_ratio_total: 0.274 -> 0.013
- sw_MLQ_total_lps_km2_upstream: 2.918 -> 0.093

Direction is consistent with the frozen low-flow definition.

## Municipality enrichment sanity review

Municipality enrichment was reviewed as a descriptive geographic check, not as a calibration target.

Examples:

### MarkTorka · high 10% enrichment

- Östra Göinge 2.78x
- Hässleholm 2.58x
- Perstorp 1.73x
- Kristianstad 1.62x
- Höör 1.50x

### MarkTorka · low 10% enrichment

- Åstorp 4.31x
- Lomma 3.31x
- Bjuv 2.85x
- Helsingborg 2.25x
- Staffanstorp 2.01x

### MarkVäta · high 10% enrichment

- Åstorp 3.94x
- Höganäs 3.09x
- Lomma 2.92x
- Staffanstorp 2.60x
- Helsingborg 2.46x

### MarkVäta · low 10% enrichment

- Osby 2.25x
- Östra Göinge 2.16x
- Hässleholm 2.15x
- Kristianstad 2.04x
- Örkelljunga 2.00x

The opposing enrichment structure of MarkTorka and MarkVäta is consistent with their related-but-distinct physical interpretation.

Groundwater and surface-water components show different municipality enrichment patterns, supporting their role as separate hydrological information.

## Contrast cases

Full-population contrast counts:

- high MarkTorka + high GrundvattenTillgång: 2,695 fields (2.095%).
- high MarkTorka + low GrundvattenTillgång: 974 fields (0.757%).
- high MarkTorka + high MarkVäta: 7 fields (0.005%).
- high GrundvattenTorka + high YtvattenTorka: 2,819 fields (2.191%).

These contrast populations are retained as interpretable combinations, not anomalies.

## Representative field cases

Minimum / median / maximum representative fields were generated for all five components and retained in the G output package for manual/UI review.

## Frozen display labels

For user-facing interpretation, the relative 0–100 component scale may be grouped as:

- 0–20: Mycket låg
- 20–40: Låg
- 40–60: Måttlig
- 60–80: Hög
- 80–100: Mycket hög

These are display bands only, not probability classes.

## Product interpretation guardrail

The five frozen component scores are relative empirical scales.

They are not probabilities, legal withdrawal rights, current-state measurements, individual-well yields or deterministic forecasts.

No combined ÅkerVatten index is defined or frozen at STOPPUNKT G.

## Next step

Proceed to product integration/UI of the five frozen components, retaining:

- score;
- display band;
- short explanation;
- raw-driver drill-down;
- explicit historical/current-state distinction for hydrological components.
