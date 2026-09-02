# Rapskartan Skåne V1 – repository discovery contract

- Upstream annotated tag: `akernorm-v1.0`
- Expected tag object: `c7f8022f13ef1fdc4560ce906e9a10c467f15c0f`
- Expected dereferenced commit: `c859a69de51a104d10f87906d4d050a34222bbb4`
- Feature branch: `feature/rapskartan-skane-v1a`
- Existing Sentinel/Copernicus implementation found at branch creation: `NO`
- Phase: `DISCOVERY ONLY — STOPPUNKT A`

The Windows runner generates the machine-specific repository, crop, geometry and access inventory
under `C:\AkerSyncRepo\work\rapskartan_skane_v1_discovery_stopA`. It never writes row-level 2025
ground truth, satellite features, predictions or models.

## Blind-test boundary

The 2025 crop label may only be opened inside the isolated aggregate inventory function at this
stage. It may not influence AOI selection, dates, cloud mask, features, model family, thresholds,
calibration or the decision to add Sentinel-1.

