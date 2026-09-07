# ÅkerPuls växtföljdsprior V1 – fryst datakontrakt

## Status

`vaxfoljd-prior-m4-v1.0-rc1` är fryst modellkontrakt-kandidat efter STOPPUNKT E. Ingen produktionsintegration, deployment, tagg eller merge ingår.

## Primär analysenhet

Fält `current_field_id` × prediktionsår `t`. Historikfeatures får endast använda `history_year < t`. Statiska features ska vara oberoende av prediktionsårets grödfacit.

## Frysta huvudinputs

- ÅkerMinne selected 2015–2025: SHA-256 `05423236dc30544f86422d42ce5c9095376a9d5dac58e6ea110f6e6702cecdcf`, 1 414 996 fältår, 128 636 referensfält.
- Static context: SHA-256 `31db31b79b53a4c0aa32621fb7bfa44165ea65b6b46371c32e4e19935f59feea`, 128 636 fält.
- ÅkerScore Soil: SHA-256 `71dfd711a4243b3cbe465de7eaa013725b2d2f9be3a8890d213a89bc095427da`, 128 636 fält.

## Målklasser

V1-priorn normaliseras över 16 agronomiska grödklasser: höstraps, höstvete, vårvete, höstkorn, vårkorn, havre, råg, rågvete, sockerbetor, matpotatis, stärkelsepotatis, vall på åkermark, majs, baljväxter, träda/miljöyta, annan gröda.

`otillräcklig historik/okänd` behålls som observations-/kvalitetstillstånd och ska inte stjäla sannolikhetsmassa från agronomiska grödor i V1.

## Featurekontrakt M4-hard

Historik H: senaste 1–3 dominanta giltiga grödor, grödspecifik tid sedan senaste observation, antal förekomster i 3/5/7/10-årsfönster, långsiktig andel, antal giltiga historikår, täckning och dominantandel.

Statik X: kommun, dominant SKO, dominant jordbruksklass/jordklass, fältareal, ÅkerScore Soil p50 samt statisk soil/context-QA.

Component-soft och ekonomi är inte del av V1.

## År-blind protokollnot

Full M4 valdes på 2021–2024. 2025 hade redan öppnats innan full M4 sluttestades och är därför endast post-holdout diagnostik. 2026 ska behandlas som nästa verkliga blindår.
