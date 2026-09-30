# ÅkerAccess — STOPPUNKT B2

B2 was introduced after the first 100-field visual review exposed three issues:

1. fields below 1 ha add disproportionate noise for the intended machinery-access product;
2. pasture/slåtteräng should not be in the ÅkerAccess product universe;
3. "candidate found" and "best candidate ranked correctly" are different questions.

## Eligibility

B2 freezes for this experiment:

- minimum field area: **1.0 ha**;
- exclude frozen ÅkerMinne 2025 fields whose official dominant crop name explicitly matches configured pasture/slåtteräng terms;
- do **not** exclude ordinary vall merely because it is grass;
- unknown crop context remains eligible rather than being silently removed.

Matched excluded crop names are written separately for audit.

## Carry-over

The user's completed v0b QA is local/private input and is never committed.

Eligible old reviews are reused. Their old labels are mechanically mapped into the B2 taxonomy and marked:

`label_source = legacy_mapped`

Fresh B2 decisions are marked:

`label_source = human_b2`

Thus later analysis can report fresh and carried-over evidence separately.

## B2 labels

- `RANK1_PLAUSIBLE`: red/rank-1 entrance is physically plausible.
- `OTHER_CANDIDATE_BETTER`: another displayed OSM candidate is the better/plausible access.
- `ACCESS_VISIBLE_NOT_CANDIDATE`: visible plausible access is not represented by the candidates.
- `NO_VISIBLE_ACCESS`: no clear entrance can be identified from imagery.
- `UNCLEAR`: imagery does not support a useful decision.
- `EXCLUDE_OTHER`: field is operationally irrelevant for another reason, e.g. greenhouse.

"Plausible" is intentional: B2 does not attempt to prove which entrance the farmer actually uses.

## Sampling

The frozen target is **20 eligible fields per STOPPUNKT A evidence class**. Existing eligible reviewed fields are kept. Only the deficit in each class is deterministically topped up.

Run:

`RUN_AKERACCESS_STOPPB2.bat`

The runner searches for the prior CSV in the work directory and the user's Downloads/Nedladdningar folder.

When all green "NYTT B2-fält" rows have been reviewed, export:

`sjobo_akeraccess_visual_qa_b2.csv`

and return it to the coding chat.
