# ÅkerVatten H0 · Stora grundvattenmagasin · FREEZE

**Status: PASS**

H0 inventories SGU Grundvattenmagasin for the frozen 2025 Skåne field population.

No new 0-100 component is created and no frozen ÅkerVatten v0a component is modified.

## Source

Official SGU bulk product:

`https://resource.sgu.se/data/oppnadata/grundvattenmagasin/grundvattenmagasin.zip`

Frozen source SHA-256:

`eaab89df11dbfeb160ad50e752cb027f1971e555c37c82ef2ae0570e33a95edd`

Layers present include:

- grundvattenmagasin
- magasinsdelomraden
- tillrinningsomraden
- ytvattenkontakter
- grundvattenstromningsriktningar
- laggenomslappligt_lager_ovan_magasin
- grundvattendelare
- karteringsmetod

## Full-Skåne inventory

Population: 128,636 fields.

Representative-point relation:

- DIRECT_MAGAZINE: 91,662 fields = 71.26%
- RECHARGE_AREA_ONLY: 2,364 = 1.84%
- NONE: 34,610 = 26.91%

Magazine position evidence:

- sedimentary S1-S3: 77,004 fields = 59.86%
- soil J1-J3: 26,186 = 20.36%
- crystalline K1: 6,293 = 4.89%

Fields with a direct match and a known SGU withdrawal/median-capacity class:

- 86,234 = 67.04%

Multiple vertically stacked magazines are preserved as separate matches.

## Withdrawal-class distribution

Most common frozen field-level best-known classes include:

- sedimentary bedrock 20,000-60,000 l/h: 16,336 fields
- sedimentary bedrock 600-2,000 l/h: 11,156
- sedimentary bedrock 2,000-6,000 l/h: 10,457
- sedimentary bedrock 6,000-20,000 l/h: 9,645
- sedimentary bedrock 60,000-200,000 l/h: 7,985
- sedimentary bedrock <600 l/h: 7,662
- >125 l/s: 5,578
- 1-5 l/s: 5,300
- <1 l/s: 4,319
- 5-25 l/s: 3,308
- 25-125 l/s: 3,197

Unknown/not-assessed classes remain unknown.

## Spatial semantics

H0 uses the deterministic representative point frozen in STOPPUNKT C.

`DIRECT_MAGAZINE` means the field representative point lies inside an SGU magazine polygon. It does not mean the full field polygon lies inside the magazine.

A mapped withdrawal opportunity / median capacity is hydrogeological screening information. It is not a vattendom, permit, legal withdrawal right, guaranteed well yield, or proof of sustainable irrigation abstraction at a specific field.

## Product implication

A simple yes/no flag for "large groundwater magazine" is insufficient in Skåne because direct magazine coverage is high.

The informative raw product dimensions are instead:

- magazine identity;
- vertical position J/S/K;
- aquifer/rock type;
- magazine subarea;
- mapped withdrawal/median-capacity class;
- recharge-area relation.

No score is frozen in H0.
