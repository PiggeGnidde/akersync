# ÅkerPass Unified Preview — U6 final web freeze

U6 is the final hosted-web gate for the unified preview release.

Prerequisites already satisfied before U6:

- U4 RC1 freeze/package/verify PASS;
- U5 exact-RC1 deploy PASS;
- hosted HTTPS machine smoke PASS;
- explicit user ACK after real-world testing in both a real mobile browser and
  the Tesla in-car browser;
- GPS / Min position, Följ mig and zoom tested successfully across the map
  layers.

U6 performs **no rebuild and no new deployment**.

It:

1. re-runs the hosted HTTPS verifier;
2. revalidates the pinned SFTP host key and exact preview webroot;
3. verifies `.htaccess` and `.htpasswd` are byte-identical to the U5 receipt;
4. validates the exact deny-all rollback directory recorded by U5;
5. removes only that rollback snapshot;
6. re-runs the hosted HTTPS verifier;
7. writes the final freeze manifest.

Run:

    CALL FINALIZE_AKERPASS_UNIFIED_U6.bat

Final frozen hosted artifact:

- RC: `akerpass-unified-preview-v0a-r1-rc1`
- SHA256:
  `01a96dda7ced90be99a686f8de081ed72fc19f0fd4b1adf556d42de7def48173`
- hosted URL: `https://preview.akerpass.se/`

Any future change to hosted web bytes requires a new release/version rather
than mutating this freeze in place.
