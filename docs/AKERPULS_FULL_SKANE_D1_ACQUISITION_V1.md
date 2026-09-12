# ÅkerPuls split-fusion QA v1 — STOPPUNKT D1 full Skåne

Status: **IMPLEMENTED; NOT YET RUN**

D1 is the first full-Skåne stage that calls the Sentinel Hub Process API. It is pinned to the final D0b execution contract SHA256:

`d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19`

Planned scope:

- 593 daily Process API requests;
- 142 aligned 1024×1024 raster tiles at 10 m;
- 568 four-snapshot tiles (April, May, June, July);
- estimated PU upper: 5534.67;
- B1/C1/C5B/C7B preprocessing semantics retained exactly;
- paired dates mosaicked only, never phenologically averaged;
- daily source tiles cached with request/response hashes and are resumable;
- four VRT mosaics built after snapshot-tile synthesis;
- no model fitting or threshold tuning;
- no crop classification;
- no automatic split, merge, or geometry replacement.

The run must verify the final D0b contract hash and D0 request-plan hash before the first Process API request. Existing verified source tiles are reused on rerun.

D1 only acquires and prepares the frozen raster evidence. Frozen split-fusion QA scoring over all 2025 fields is deferred to D2.
