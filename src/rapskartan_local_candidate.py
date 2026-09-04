"""Opt-in offline candidate; never selected by the production map runner.

Mask constants match OpenJDK 17 Marlin (256 x 8 subpixels, quarter-biased
8-bit alpha). This rasterio implementation matches the four supplied nonempty
reference masks, not a claim of equivalence for every possible geometry.
"""
from __future__ import annotations

import numpy as np
from affine import Affine
from rasterio.features import rasterize
from shapely.affinity import affine_transform

PROFILE = "reference_pixels_v2"
MAX_SUBPIXEL_BYTES = 16 * 2**20


def reference_polygon_mask(geometry, transform, out_shape, *, max_bytes=MAX_SUBPIXEL_BYTES):
    """Bounded row stripes; alpha = (coverage*255 + 2048//4)//2048."""
    height, width = out_shape
    if height < 1 or width < 1 or geometry.is_empty or not geometry.is_valid:
        raise ValueError("Invalid reference-mask geometry or dimensions")
    row_bytes = width * 256 * 8
    if row_bytes > max_bytes:
        raise RuntimeError("Candidate subpixel row exceeds memory guard")
    rows_per_stripe = max(1, max_bytes // row_bytes)
    inverse = ~transform
    polygon = affine_transform(geometry, [inverse.a, inverse.b, inverse.d, inverse.e, inverse.c, inverse.f])
    result = np.zeros((height, width), dtype=bool)
    for start in range(0, height, rows_per_stripe):
        rows = min(rows_per_stripe, height-start)
        high = rasterize([(polygon, 1)], out_shape=(rows*8, width*256),
                         transform=Affine(1/256, 0, 0, 0, 1/8, start),
                         fill=0, dtype="uint8", all_touched=False)
        coverage = high.reshape(rows, 8, width, 256).sum(axis=(1,3), dtype=np.uint32)
        result[start:start+rows] = (coverage*255+512)//2048 > 0
    return result


def reference_reflectance(interpolated_dn, scale, offset):
    """Candidate: truncate nonnegative DN, apply scale/offset, harmonize >=0.

Quantization occurs after bilinear interpolation, before index calculations.
No per-field adjustments or source-tile seam heuristics are applied.
"""
    if scale <= 0 or not np.isfinite(scale) or not np.isfinite(offset):
        raise ValueError("Invalid radiometric scale/offset")
    values = np.maximum(np.floor(interpolated_dn) + offset/scale, 0)*scale
    return values.astype(np.float32)


def reference_percentiles(values):
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Reference percentiles require finite samples")
    return np.percentile(values, [10,50,90], method="higher")


def reference_metrics(bands):
    # Recover the quantized reflectance input as double, not rounded TIFF input.
    b = {name: np.rint(value.astype(np.float64)*10000)/10000 for name,value in bands.items()}
    def ratio(a, c):
        return np.divide(a-c, a+c, out=np.zeros_like(a), where=np.abs(a+c)>1e-12)
    ndvi = ratio(b["B08"],b["B04"])
    values = {**b, "NDVI":ndvi, "NDRE":ratio(b["B8A"],b["B05"]),
              "EVI2":2.5*(b["B08"]-b["B04"])/(b["B08"]+2.4*b["B04"]+1),
              "GNDVI":ratio(b["B08"],b["B03"]), "LSWI":ratio(b["B08"],b["B11"]),
              "NIRV":b["B08"]*ndvi, "YELLOWNESS":ratio(b["B03"],(b["B02"]+b["B04"])/2)}
    return {name:value.astype(np.float32) for name,value in values.items()}
