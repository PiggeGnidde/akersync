# ÅkerPuls preliminära skiften 2026 – arbetskontrakt V0

Denna gren är isolerad från den frysta 2025-geometrin och ÅkerMinne. Basen är taggen
`akerpass-akerminne-context-v1.0`, commit `1ad5c77656bb93664d94254af298009a6620da4f`.

## Frysta snapshots

- `S2_2026_APRIL`: 2026-04-08 + 2026-04-09
- `S2_2026_MAY`: 2026-05-25
- `S2_2026_JUNE`: 2026-06-26 + 2026-06-27
- `S2_2026_JULY`: 2026-07-09

Tvådagarsparen är samma regionala snapshot. Vid överlapp skall mosaikbyggaren välja
klar pixel först och annars lägst CLD; den får aldrig medelvärdesbilda 8/9 april eller
26/27 juni som fenologiska observationer.

## STOPPUNKT A0

A0 är en säker preflight före STOPPUNKT A. Den får endast:

1. verifiera exakt fryst 2025-skiftesfil (128 636 geometrier + SHA256),
2. inventera CDSE STAC-scener på de sex frysta datumen,
3. mäta footprint-coverage mot unionen av 2025-skiften,
4. bygga en lokal 10 m tile-plan,
5. estimera antal Process API-anrop och PU,
6. göra ett 32×32 pixlar autentiserat Process API-smoke mot 2026-05-25.

A0 får inte masshämta Sentinel-data eller skapa preliminära 2026-geometrier.

När A0 är accepterad implementeras STOPPUNKT A som fyra lokala, molnmaskade tile-mosaiker.
Första datalagret hålls avsiktligt begränsat till B02/B03/B04/B08/B11 + SCL/CLD/dataMask;
NDVI och LSWI kan då beräknas exakt. Red-edge läggs till först om pilot B visar att det
behövs, för att hålla PU/storage nere.
