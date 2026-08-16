# Geometry validation roadmap

## What the current regression validates

The current Geometry V1a regression uses 2025 crop/land-use choice as the target. It therefore measures a **human revealed-preference signal**: given the field geometry, what land use did farmers actually choose?

This is valuable empirical validation, but it is not direct evidence of machine efficiency. Human land-use decisions also reflect economics, soil, history, environmental rules, ownership, rotation, drainage and other factors.

## Independent future validation: machine simulation

A separate future track should estimate machine-operational efficiency directly from field polygons. This should be kept independent from the human land-use regression so that agreement between the two becomes genuine convergent validation rather than circular calibration.

Candidate simulation outputs include:

- total route / working distance per hectare,
- non-working distance per hectare,
- number of turns,
- headland share,
- effective mean run length,
- time per hectare under explicit speed/turn assumptions,
- overlap / missed-area proxy,
- sensitivity to implement width (for example 6 m, 9 m and 12 m),
- optimal driving direction.

Fields2Cover or an equivalent open-source coverage-planning engine is a candidate implementation path.

## The key future question

Do the fields that farmers appear to prefer for active cultivation also rank as efficient fields in an independent machine simulation?

Useful comparison metrics:

- Spearman rank correlation between human-derived geometry preference and machine-efficiency metrics,
- overlap in top/bottom deciles,
- regression of simulated machine efficiency on the same raw Geometry V1a descriptors,
- stability across machine widths and routing assumptions.

If both the human-choice data and the independent machine simulation select similar fundamental geometry descriptors, that would be substantially stronger validation of the Field Fingerprint / ÅkerPass geometry concept than either source alone.
