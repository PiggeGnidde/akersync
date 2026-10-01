# ÅkerFrö × ÅkerAccess web v0b — whole-Skåne screening

This stage comes before BestMatch freeze and before ÅkerKombinatorik.

It builds on the already existing real ÅkerFrö web application rather than replacing the municipality-based ÅkerPass UI.

The existing municipality ÅkerFrö layer remains unchanged. A new Hela Skåne button switches to a whole-Skåne screening overlay containing the union of the top 5,000 fields from the three D5 policies plus BestMatch v0a and frozen C10 baseline.

The user can switch ranking and top 200/500/800/1000/2000/5000 without resetting viewport. The field drawer shows customer-facing road labels and exposes whether D5 had to fall back to straight-line Bjuv distance.

Existing real web dist is auto-discovered but never modified. A separate preview dist is produced at dist_akerfro_access_v0b. D5 remains candidate-only and is not frozen by this build.

Run:

CALL RUN_AKERFRO_ACCESS_WEB_V0B.bat

CALL START_AKERFRO_ACCESS_WEB_V0B.bat

Default local preview: http://localhost:8011/
