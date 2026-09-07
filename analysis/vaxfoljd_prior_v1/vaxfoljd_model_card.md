# Model card – ÅkerPuls växtföljdsprior M4 V1

## Modell

**Vald modell:** M4-hard multiclass.

**Syfte:** ge en pre-satellite prior `P(C_t=c | H_t, X)` per fält och år, inte ett påstående om observerad gröda.

## Varför M4

- M1 första ordningens Markov är otillräcklig för fleråriga crop-hazards.
- M2 visar verklig semi-Markov/hazard-struktur men räcker inte ensam.
- M3 med hela historiken förbättrar log-loss tydligt.
- Full M4 förbättrar M3 i varje utvecklingsår 2021–2024; medel-log-loss 0,90841 → 0,88171, relativ förbättring 2,94 %.
- M5 ekonomi gav endast +0,066 % genomsnittlig raps-log-loss gain 2022–2024 och instabilt tecken; ej produktval.

## Hyperparametrar för fryst M4-kandidat

LightGBM multiclass; n_estimators=35, num_leaves=31, learning_rate=0.12, min_child_samples=100, colsample_bytree=0.7, reg_lambda=5.0, random_state=20260907.

## Viktiga diagnostiska resultat

Raps-hazard toppar kring 4–6 år efter senaste dominanta raps. Vid samma kandidatandel som hårt 10-årsfilter gav full multiclass M4 2025-diagnostiskt 96,54 % recall mot 79,33 % för hårdfiltret. En separat raps-specifik ablation visade att huvuddelen av förbättringen kommer från hela rotationssekvensen: 707 av de 813 hårdfiltermissarna återfanns redan av M3-hard i den ablationen. Component-soft är informativt men inkrementellt.

## Begränsningar

- 2025 full M4 är inte ett nytt blindresultat.
- Fält tillhör samma brukare utan observerat farmer-ID; observationer är därför inte fullt oberoende.
- ÅkerMinne är en geometriskt/administrativt rekonstruerad historik med split/merge/coverage-osäkerhet.
- M4-soft har endast raps-specifik ablation, ej full multiclass validering.
- Ekonomi har litet effektivt tids-N och ingår inte i V1.

## Rekommenderad användning

Använd hela sannolikhetsvektorn, top-k, entropi och sannolikhetströsklar. Använd aldrig historik som veto. Satellitbearbetning kan prioriteras efter priorn men alla fält måste kunna återkomma via satellitevidens.
