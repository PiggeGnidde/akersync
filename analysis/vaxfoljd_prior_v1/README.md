# ÅkerPuls växtföljdsprior V1 – Git freeze candidate

## Status

`vaxfoljd-prior-m4-v1.0-rc1` är fryst modellkontrakt-kandidat efter STOPPUNKT E.

Denna branch innehåller endast kontrakt, modellkort, formler, små QA/resultattabeller och verifieringskod. Rådata, parquet och freeze-ZIP lagras lokalt och identifieras med SHA-256.

**Ingen merge, tagg, deployment eller produktionsintegration ingår i denna commit.**

## Branch och lineage

- Branch: `feature/akerpuls-vaxfoljd-prior-v1a`
- Bas: combined context commit `1ad5c77656bb93664d94254af298009a6620da4f`
- ÅkerMinne: tag `akerminne-v1.0`, commit `4b53ab24e9822f1c36c6cc31931dba3c1855fead`
- Validation: tag `akerscore-akerminne-validation-v1.0`, commit `9ca92418d6c100793dcaf3ae70705c97e556a9d5`

## Modellbeslut

Vald V1-prior är **M4-hard multiclass**. Modellvalet baseras på 2021–2024. Full-M4-resultat för 2025 är post-holdout diagnostik och 2026 är nästa verkliga blindår.

M4-soft är dokumenterad som lovande men ej vald efter endast raps-specifik ablation. M5 ekonomi är NO-GO för V1 efter instabil och mycket liten unseen-year förbättring.

## Lokal freeze

Förväntad lokal katalog:

`C:\AkerSyncRepo\work\vaxtfoljd_prior_v1_freeze`

Förväntad ZIP:

`vaxfoljd_prior_v1_freeze.zip`

SHA-256:

`bb6be8437027573a525c8344c34ce372e49b867ec52a67f2466475d6cf60ce6e`

Verifiera från repo-roten:

`VERIFY_VAXTFOLJD_PRIOR_V1_FREEZE.bat`

## Git-innehåll

- `vaxfoljd_data_contract.md`
- `vaxfoljd_model_card.md`
- `vaxfoljd_prior_formulas.md`
- `vaxfoljd_freeze_manifest.json`
- `results/` med små låsta resultattabeller
- `VERIFY_VAXTFOLJD_PRIOR_V1_FREEZE.bat`
- `analysis/vaxfoljd_prior_v1/verify_vaxfoljd_prior_v1_freeze.py`

Technical Note DOCX ligger i den lokala ZIP:en och är hash-låst i manifestet, men checkas inte in som binär Git-artefakt i denna kandidat.
