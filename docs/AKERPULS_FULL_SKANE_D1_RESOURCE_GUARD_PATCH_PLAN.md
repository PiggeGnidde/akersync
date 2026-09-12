# D1 dynamic disk/token guard plan

Before D1 is run, two operational guards are required:

1. Disk-space guard is based on **remaining** theoretical uncompressed daily-source and snapshot-tile bytes plus reserve, not a fixed first-run threshold. This preserves resumability after a partial run.
2. CDSE OAuth token is refreshed periodically during the 593-request acquisition so a long run cannot fail merely because one access token expires.

These are execution-safety changes only. They do not alter Sentinel preprocessing, frozen dates, fusion, thresholds, or geometry policy.
