# Rapskartan Skåne V1 – Sentinel-2 L2A access discovery

- Retrieved UTC: `2026-09-02T19:28:54.210010+00:00`
- Public STAC smoke: `PASS`
- Authenticated Process API pixel smoke: `PASS`
- Collection: `sentinel-2-l2a`
- Smoke AOI: fixed 0.01° box near Lund; not selected from crop labels.
- Smoke period: `2024-04-01T00:00:00Z/2024-04-30T23:59:59Z` (before blind year)
- Pixel request: `32×32`; `B04, B08, SCL, dataMask`
- Request SHA256: `bd7264c7e65fd8a371a0679a8305f846c5d988001d3df902ed687f336ca8ee89`
- OAuth secrets logged or persisted: `NO`
- Pixel payload persisted: `NO`
- STAC item: `S2A_MSIL2A_20240430T102021_N0510_R065_T33UUB_20240430T143850` at `2024-04-30T10:20:21.024000Z`
- STAC response SHA256: `45037f9c65224fcba8a3280447bcb7fd70c26af955663671588318b5407d358a`
- Process response: `8261` bytes; SHA256 `68b536832275583ec6b3b92089e33222650830fa2ec6e05be4a2d159f1ff4f89`
- Processing units reported: `0.02`

## API and credentials

- STAC collection: `https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a`
- STAC search: `https://stac.dataspace.copernicus.eu/v1/search`
- OAuth token endpoint: `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
- Process API: `https://sh.dataspace.copernicus.eu/process/v1`
- Local environment names: `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET`.
- Reuse OAuth tokens until expiry; do not request one token per API call.

## Bands and quality inventory

Required next-pilot inventory: B02, B03, B04, B05, B06, B07, B08, B8A, B11, B12, SCL, dataMask and CLD if reproducible.
No cloud mask is frozen here. The S2 pilot must verify exact SCL codes and explicitly exclude no-data, saturated/defective, shadow, medium/high cloud, cirrus, snow/ice and relevant water pixels.

## Cache and storage estimate

- Uncompressed seven-year upper planning equivalent: `379.6` GiB.
- Recommended bounded source-cache envelope: `200–800` GiB.
- Recommended derived field-aggregate envelope: `1–5` GiB.
- First S2 pilot cache bound: `2–10` GiB.
- Cache root: `C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a`.
- Estimate only; no allocation or mass download has been performed.

Official documentation: https://documentation.dataspace.copernicus.eu/APIs/STAC.html
OAuth: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html
Process API: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html
Quotas: https://documentation.dataspace.copernicus.eu/Quotas.html
