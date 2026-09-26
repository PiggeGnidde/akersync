# ÅkerFrö Operational MVP v0a – formal freeze

## Scope

Denna freeze låser den produktnära kedjan **C8b + C9 + C9b + C10** ovanpå redan formellt fryst ÄrtMatch v0a.

Fryst policy:

- kandidatår 2026,
- hög ÄrtMatch = topp 20 % av scorebara fält,
- 6-årig observerad rotations-caution,
- A-förfruktsprior kräver minst 50 historiska positiva händelser,
- AreaFit med bred 5–12 ha-platå,
- monotont BjuvProximity utan hårt avståndsveto,
- AreaLogistik = 0.55 AreaFit + 0.45 BjuvProximity,
- ranking = C8-klass -> AreaLogistik -> fryst ÄrtMatch -> field-id.

## Populationsankare

- 128,636 fält
- A = 7,847
- B = 14,882
- C = 1,424
- D = 104,483
- C9b A/B-universum = 22,729
- historiska positiva i C9b-universum = 590
- C10 HIGH = 20,327
- C10 MEDIUM = 34,060
- C10 LOW = 74,249

## Semantik

Denna freeze låser en **MVP-produktpolicy**, inte ett agronomiskt sannolikhetsmått.

ÄrtMatch v0a förblir separat och read-only.

Area och Bjuv-avstånd är operativa historiska selektionssignaler. De får inte tolkas som biologisk lämplighet.

## Utanför freeze

- kontraktstillgång,
- bevattning/vattenrisk,
- farmer-ID, maskinpark och management,
- faktisk 2026-gröda,
- väg-/skördetid till processor.

## Lokal freeze

Kör:

    FREEZE_AKERFRO_OPERATIONAL_MVP_V0A.bat

Det skapar:

    work/akerfro_ertor_v0a/operational_mvp_v0a_freeze/akerfro_operational_mvp_v0a_freeze_manifest.json

Manifestet innehåller SHA-256 och filstorlek för kod, config och centrala outputs.

Verifiera därefter när som helst:

    VERIFY_AKERFRO_OPERATIONAL_MVP_V0A_FREEZE.bat

Efter PASS ska C8b/C9/C9b/C10 behandlas som read-only. Nya vatten-, bevattnings-, processor- eller andra lager byggs downstream som nya steg.
