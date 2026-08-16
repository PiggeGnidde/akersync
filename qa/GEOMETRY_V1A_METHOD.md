# ÅkerSync · Geometry V1a

Geometry V1a measures transparent raw descriptors on Jordbruksverket 2025 **skifte** polygons. It deliberately does **not** create a composite Geometry Score or claim to measure total field quality.

The goal is to establish interpretable physical descriptors, inspect their distributions and visual extremes, and later validate them against experienced machine operators before choosing score weights or a track-planning model.

## Primary descriptors

### Area

`area_ha = polygon area / 10,000`

Field size matters because short fields create more turning and setup overhead per cultivated hectare.

### Minimum rotated bounding rectangle (MBR)

For each skifte, the minimum-area rotated rectangle enclosing the polygon is calculated.

Outputs:

- `mbr_area_ha`
- `mbr_long_m`
- `mbr_short_m`
- `mbr_aspect_ratio = mbr_long_m / mbr_short_m`
- `mbr_long_axis_deg_from_north`

Orientation is a 0–180° bearing clockwise from north: 0° = north–south and 90° = east–west. For near-square fields (`aspect_ratio < 1.05`) the orientation is marked unstable because the long axis is not physically meaningful.

### Rectangularity

`rectangularity = field_area / MBR_area`

A perfect rectangle has value 1. Lower values mean the enclosing working rectangle contains more area outside the actual field.

### Convexity

`convexity = field_area / convex_hull_area`

A convex field approaches 1. Indentations and concave corners lower the value.

### Simple effective-run-length proxy

`erl_proxy_m = field_area_m2 / mbr_short_m`

Interpretation: if the field were worked parallel to the MBR long axis, area divided by nominal working width across the field gives an equivalent mean run length. This is only a V1 proxy; it does not simulate parallel machine tracks, multiple segments, headlands, entrances or obstacles.

### Perimeter / complexity diagnostics

Outputs include:

- total boundary length
- exterior perimeter
- hole perimeter
- perimeter per hectare
- component count
- largest component share
- number and area of holes
- compactness `4πA/P²`

These are diagnostics, not direct machine-cost estimates.

## Important limitations

Geometry V1a does **not** include:

- headland modelling
- machine width
- actual field entrances
- poles, trees or other internal obstacles unless they appear as polygon holes
- slope constraints
- wet areas
- drainage
- crop-specific operations
- turn radius
- actual AB-lines / GNSS driving logs
- fuel or time cost

A later V2 may evaluate explicit parallel-track simulation (for example with Fields2Cover) and compare a real field with an ideal same-area reference field for standardized machine widths.

## Outputs

- `data/derived/geometry_v1a_skiften.csv`
- `data/derived/geometry_v1a_summary.csv`

No composite score is written by V1a.
