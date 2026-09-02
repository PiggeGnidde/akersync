# Rapskartan Skåne V1 – Sentinel-2 access contract

Discovery uses Copernicus Data Space Ecosystem only:

- public STAC collection: `https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a`
- public STAC search: `https://stac.dataspace.copernicus.eu/v1/search`
- OAuth token: `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
- Process API: `https://sh.dataspace.copernicus.eu/process/v1`

The reproducible smoke request is fixed before blind-label access: a 32×32 pixel request near Lund,
April 2024, with B04, B08, SCL and dataMask. The AOI is a fixed coordinate box and was not selected
using any crop label. Only request/response hashes and response size are retained.

Credentials are read from `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`. Their values must never be
written to Git, logs, manifests or chat. Missing credentials yield `BLOCKED_CREDENTIALS`.

No SCL mask, feature set or model is frozen at STOPPUNKT A. Exact quality-mask semantics are deferred
to the separately approved Sentinel-2 data pilot.

