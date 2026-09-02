# ÅkerNorm V1 – slutlig freeze

Denna freeze promoverar den verifierade modellkandidaten `akernorm-v1.0-rc1` till den immutabla produktversionen `akernorm-v1.0`. Modellvärdena ändras inte vid promoveringen.

## Låst produkt

- Annoterad tagg: `akernorm-v1.0`
- Branch: `feature/akernorm-product-v1a`
- Accepterat produktträd före freeze-metadata: `5a938a72dd978a3b529834bd0a8c2aef09292100`
- Officiell källsnapshot: `akernorm-source-2026-f03930b8a2a063de`
- Modellmanifest: `akernorm-model-def3710a77e7ace9`
- Full Skåne-manifest: `akernorm-full-skane-38d679e0f59c3ae0`
- Fullt resultathash: `38d679e0f59c3ae0326661cabffe363c21ae15622a491fdb5cceb6e4e3635e6e`
- Omfattning: 33 kommuner, 128 636 skiften och 402 922 skifte/gröda-rader

## Godkända grindar

- STOPPUNKT A: discovery och reproduktion PASS.
- STOPPUNKT B: fryst modellkandidat och avgränsad pilot PASS.
- STOPPUNKT C: full Skåne, referenskonservation och checkpointstabilitet PASS.
- STOPPUNKT D: kommunvis lazy webb, årsberoende officiella grödnamn och varningsförklaringar PASS.
- ÅkerScore, ÅkerVärde, ÅkerDrift och ÅkerMinne är byte-identiska med den frysta baswebben.

`src/88_verify_akernorm_v1_freeze.py` återhashar de accepterade artefakterna och de tre frysta indatafilerna. Fyratimmarskörningen behöver därför inte räknas om för taggningen. Den slutliga freeze-committen får endast innehålla detta dokument, freeze-runnern, slutverifieraren och dess test.

## Utanför denna freeze

- Ingen merge.
- Ingen deployment eller publicering av webb.
- Ingen Sentinel-2-implementation eller Sentinel-2-körning.
- Taggen får aldrig flyttas eller force-pushas. En korrigering kräver ny commit och ny versionstagg.
