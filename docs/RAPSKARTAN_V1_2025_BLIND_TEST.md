# Rapskartan Skåne V1 – 2025 blindtest

Detta steg implementerar endast Fas D och STOPPUNKT D i den bindande
implementationsspecifikationen.

## Processgräns

1. Läs endast identitet, kommun och geometri ur 2025 års skifteskälla.
2. Skapa ett deterministiskt, kommun- och arealstratifierat urval om högst
   3 300 fält.
3. Bygg ÅkerMinne-prior från 2021–2024 och Sentinel-2-features fram till var
   och en av de nio frysta informationsdatumen.
4. Kör exakt de 27 frysta modellpaketen från accepterad STOPPUNKT C.
5. Skriv predictions utan målvariabel och lås alla pre-label-artefakter med
   SHA-256 i `prediction_lock_manifest.json`.
6. Starta en separat process som först verifierar hela låset och därefter
   öppnar den hash-låsta 2025-ground-truth-filen.
7. Beräkna blindmått, confusion matrices, kalibrering, rumslig QA,
   datakvalitet och kartbara felurval utan modell- eller tröskeljustering.
8. Kör en oberoende verifierare som räknar om predictions och resultat.

## Körning

Kör `RUN_RAPSKARTAN_2025_BLIND_TEST.bat` och därefter
`VERIFY_RAPSKARTAN_2025_BLIND_TEST.bat` i samma rena feature-worktree som
STOPPUNKT C. Copernicus-variablerna `CDSE_CLIENT_ID` och
`CDSE_CLIENT_SECRET` ska finnas i det aktuella `cmd.exe`-fönstret.

Första körningen gör högst 3 300 autentiserade fältförfrågningar och kan ta
1–3 timmar. Svar lagras i en innehållsadresserad cache. En omkörning återspelar
cachen och verifierar byte-identiska feature- och predictionfiler.

## Förbjudet i detta steg

Ingen 2025-label får användas före predictionslåset. Ingen modell, feature,
kalibrering eller threshold får ändras efter att låset öppnats. Steget kör inte
full Skåne-export, Sentinel-1, webbkarta, deployment, tagg eller merge.
