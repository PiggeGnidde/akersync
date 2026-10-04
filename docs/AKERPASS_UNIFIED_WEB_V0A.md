# ÅkerPass Unified Preview Web v0a

## Scope

This r1 integration starts from frozen ÅkerFrö Rotation v1.1 and BestMatch v0c and builds one local preview containing:

- existing ÅkerPass / ÅkerNorm core,
- ÅkerFrö,
- frozen ÅkerAccess v0a,
- frozen ÅkerFrö Rotation v1.1 municipality classification,
- frozen BestMatch v0c (same 50/25/25 policy as v0b, Rotation v1.1 eligibility),
- frozen ÅkerVatten plus VISS/VattenTryck v1,
- Rapskartan 2025 as the separate sub-view \`/rapskartan25/\`.

No model is recalculated and no new combined ÅkerPass or ÅkerVatten score is created.

## Important integration rule

The unified build does **not** use the old ÅkerVatten index.html as its base.

It first regenerates the Access/BestMatch presentation from the canonical frozen BestMatch v0c table. It then patches exactly the 43 formally frozen Rotation v1.1 boundary-spill releases into the copied municipality ÅkerFrö sidecars; the source ÅkerFrö web is never modified. It then auto-discovers the already-built final ÅkerVatten-VISS web dist and forward-ports only:

- \`data/akervatten/*\`
- \`assets/akervatten_v0a.css\`
- \`assets/akervatten_v0a.js\`

The final VISS payload must contain the frozen VattenTryck v1 markers and anchors:

- 128,636 fields,
- 16,626 fields with a positive VISS case,
- 5,495 fields carrying the frozen groundwater-level-impact flag.

Rapskartan is copied unchanged except for a deterministic backlink to the main ÅkerPass view.

## U2 run

\`\`\`bat
CALL BUILD_AKERPASS_UNIFIED_WEB_V0A.bat
\`\`\`

The wrapper first re-verifies frozen Rotation v1.1 and BestMatch v0c, then builds the unified dist and runs the independent unified verifier. The verifier checks all 43 municipality-sidecar releases plus the Staffanstorp regression case (2A/2B released; 94A remains caution).

Expected stop:

\`\`\`text
AKERPASS UNIFIED WEB U3-R1: BUILD PASS / VERIFY PASS
\`\`\`

Output:

\`\`\`text
dist_akerpass_unified_v0a
work/akerpass_unified_web_v0a/build_manifest.json
work/akerpass_unified_web_v0a/verification.json
work/akerpass_unified_web_v0a/dist_manifest.json
\`\`\`

Start local QA:

\`\`\`bat
CALL START_AKERPASS_UNIFIED_WEB_V0A.bat
\`\`\`

Default URL:

\`\`\`text
http://localhost:8012/
\`\`\`

## Autodiscovery

The builder searches common \`C:\AkerSync*\` worktrees for:

1. a completed ÅkerVatten dist containing both \`AKERVATTEN_WEB_UI_V0A\` and \`AKERVATTEN_VISS_UI_V0A\`, with the frozen VISS sidecar anchors;
2. an existing Rapskartan 2025 web directory or ZIP.

If an artifact lives outside the normal AkerSync worktrees, run the Python builder directly with \`--water-viss-dist\` and/or \`--rapskartan\`.

## Freeze boundaries

The integration must not change:

- ÅkerAccess v0a score,
- Rotation v1.1 release policy,
- BestMatch v0c weights or class ordering,
- ÅkerVatten evidence dimensions,
- VISS/VattenTryck v1 semantics or provenance,
- Rapskartan model.

UI changes are allowed only if those frozen semantics remain intact.
