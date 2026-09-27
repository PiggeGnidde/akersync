# ÅkerVatten MVP v0a · STOPPUNKT F4 zero-aware organic wetness review

F3 showed that organic-soil information is largely independent of clay, TWI and the existing MarkVäta candidate, but a standard empirical percentile transform was inappropriate because the organic-share variable has a very large point mass at zero.

F4 therefore uses a hurdle transform:

- missing raw organic share -> missing;
- raw organic share = 0 -> organic evidence score 0;
- raw organic share > 0 -> empirical CDF rank among positive observations only.

This guarantees that "no organic evidence" remains zero instead of receiving a mid-percentile score because many observations are tied at zero.

F4 compares four transparent MarkVäta variants:

1. the original F arithmetic 50/50 clay + TWI candidate;
2. minimum_AND = min(clay percentile, TWI percentile);
3. organic_OR_min_hurdle = max(minimum_AND, zero-aware organic percentile);
4. organic_OR_min_rawshare = max(minimum_AND, raw organic field-share percentage).

The raw-share OR is retained as an interpretability benchmark because organic_ge20_share_pct is already on a 0–100 percentage scale.

F4 reports:

- verification that raw zero maps to zero;
- score distributions and Spearman correlation versus MarkTorka;
- top-decile overlap with MarkTorka;
- number of fields newly promoted to high wetness by the organic branch;
- missing-data coverage for mineral-wetness and organic branches.

No MarkVäta definition is frozen automatically by F4.
