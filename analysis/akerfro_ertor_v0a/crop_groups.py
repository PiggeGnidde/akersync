#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from typing import Any

CONSERVART = "CONSERVART"
OTHER_PEA = "OTHER_PEA"
FABA_BEAN = "FABA_BEAN"
OTHER_LEGUME = "OTHER_LEGUME"
PRIMARY_GROUPS = (CONSERVART, OTHER_PEA, FABA_BEAN)


def normalize_crop_name(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return " ".join(text.split())


def akerfro_crop_group(crop_name: Any) -> str | None:
    """Map an official crop *name* to an ÅkerFrö semantic group.

    Deliberately takes no numeric crop code. The numeric code is resolved by
    ÅkerMinne's year-specific CropRegistry first; this function only classifies
    the resulting official label.
    """
    name = normalize_crop_name(crop_name)
    if not name:
        return None

    # Order matters: "Ärter (ej konservärter)" contains the word konservärter.
    if re.match(r"^konservärter?\b", name):
        return CONSERVART
    if re.match(r"^ärter?\b", name):
        return OTHER_PEA
    if "åkerbön" in name:
        return FABA_BEAN

    # Relevant pulse/legume labels kept separate from the three primary groups.
    other_tokens = (
        "kikärt", "bruna bön", "bönor", "böna", "sojabön", "soja",
        "lupin", "vicker", "baljväxt", "lins",
    )
    if any(token in name for token in other_tokens):
        return OTHER_LEGUME
    return None
