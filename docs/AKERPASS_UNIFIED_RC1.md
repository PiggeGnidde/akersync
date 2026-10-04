# ÅkerPass Unified Preview v0a-r1 — U4 RC1

U4 freezes the exact unified dist that passed U3 integration and visual QA.
It deliberately does **not** rebuild the web during packaging.

## Frozen RC anchors

- dist files: 187
- Rotation v1.1 releases in municipality sidecars: 43/43
- Rotation priority presentation: 37 BestMatch v0c ranks + 6 explicit D0 <1 ha exclusions
- BestMatch v0c candidates: 16,004
- BestMatch v0c whole-Skåne screening union: 5,000
- ÅkerVatten fields: 128,636
- VISS positive fields: 16,626
- groundwater-level-impact fields: 5,495
- Rapskartan 2025: present
- no new total score
- no water legal assessment

## U4 run

    CALL PACKAGE_AKERPASS_UNIFIED_RC1.bat

The wrapper verifies the two upstream freezes, re-verifies the existing
QAed unified dist, packages it and then re-opens the ZIP and hashes every
member against the frozen dist manifest.

Canonical deploy package:

    release/akerpass_unified_preview_v0a_r1_rc1.zip

RC manifest:

    work/akerpass_unified_rc1/akerpass_unified_preview_v0a_r1_rc1_manifest.json

The ZIP has the web root directly at ZIP root; `index.html` is not wrapped in
an extra directory.

## U5 gate

RC1 is not a production freeze. After deployment to `preview.akerpass.se`,
perform real HTTPS/mobile smoke testing:

- VISS layer on a real phone,
- field drawer/touch layout,
- Min position permission + location,
- Följ mig ON/OFF while moving,
- pan/zoom interaction with follow mode,
- municipality/layer switching,
- Rapskartan navigation and backlink.

Any modification of the RC1 dist requires RC2 or later. U6 is the final web
freeze after the U5 hosted/mobile smoke passes.
