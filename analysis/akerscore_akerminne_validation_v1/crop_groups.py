#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen crop-group definitions for ÅkerScore × ÅkerMinne validation v1.0.

The primary validation endpoints are:
- cereal_share
- vall_share

The broad-production endpoint is secondary and intentionally transparent:
it is a name-based working definition intended as a robustness measure, not
an official Jordbruksverket crop taxonomy.

All shares are calculated only over ÅkerMinne field-years with status
SINGLE_CROP.
"""
from __future__ import annotations

import pandas as pd

CEREAL_PATTERN = (
    r"Vete|Korn|Havre|Råg|Rågvete|Blandsäd|Spannmålsförsök|spannmål"
)

# Protein/cereal mixtures are not counted as "cereal" in the primary endpoint.
CEREAL_EXCLUDE_LITERAL = "Proteingrödsblandningar"

VALL_LITERALS = (
    "Slåtter och betesvall",
    "Slåttervall på åker",
)
VALL_EXACT = "Undantag 2023 miljöyta. Används för vall"

BROAD_PRODUCTION_PATTERN = (
    r"Raps|Sockerbet|potatis|ärter|Åkerbön|Sötlupin|Majs|grönsak|lök|"
    r"morot|sallat|kål|broccoli|spenat|pumpa|rödbet|sparris|jordärtskock|"
    r"krydd|selleri|gurka|palsternack|rabarber|purjolök|Oljelin|Hampa|"
    r"Solros|foderbet|Konservärter|Fruktodling|Jordgubbsodling|bärodling"
)


def classify_crop_names(names: pd.Series) -> pd.DataFrame:
    """Return deterministic boolean endpoint flags for dominant crop names."""
    n = names.fillna("").astype(str)

    cereal = (
        n.str.contains(CEREAL_PATTERN, case=False, regex=True)
        & ~n.str.contains(CEREAL_EXCLUDE_LITERAL, case=False, regex=False)
    )

    vall = (
        n.str.contains(VALL_LITERALS[0], case=False, regex=False)
        | n.str.contains(VALL_LITERALS[1], case=False, regex=False)
        | n.eq(VALL_EXACT)
    )

    broad = (
        cereal
        | n.str.contains(BROAD_PRODUCTION_PATTERN, case=False, regex=True)
    )

    return pd.DataFrame(
        {
            "is_cereal": cereal.astype(bool),
            "is_vall": vall.astype(bool),
            "is_broad_production": broad.astype(bool),
        },
        index=names.index,
    )
