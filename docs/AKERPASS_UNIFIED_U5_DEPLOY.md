# ÅkerPass Unified Preview — U5 one.com deployment

U5 deploys the exact frozen RC1 package to **preview.akerpass.se** and then
performs hosted HTTPS smoke verification. The RC itself is never rebuilt.

## Why SFTP

one.com exposes domain-specific SFTP settings in the control panel. On newer
servers, each domain/subdomain has a separate webroot shown under Subdomains,
often as `/webroots/<hash>`.

## One-time setup

    CALL SETUP_AKERPASS_U5_ONECOM.bat

The setup asks only for:

- one.com SFTP host, port, username and password,
- the **preview** subdomain Folder/root shown by one.com,
- the existing preview HTTP Basic Auth username/password.

Secrets are written to local `.env`, which is gitignored. The SFTP server
host key is pinned on first setup.

Hard safety guard: setup refuses the remote root unless it already contains
both `.htaccess` and `.htpasswd` and the auth configuration looks like the
existing protected ÅkerPass preview.

## Deploy exact RC1

    CALL DEPLOY_AKERPASS_U5_RC1.bat

The deploy:

1. verifies RC1 SHA256
   `01a96dda7ced90be99a686f8de081ed72fc19f0fd4b1adf556d42de7def48173`;
2. reconnects only to the pinned SFTP host key and confirmed preview root;
3. uploads all 189 RC files to a hidden deny-all staging directory;
4. preserves `.htaccess` and `.htpasswd` byte-for-byte;
5. moves the previous preview into a hidden deny-all rollback directory;
6. commits the staged RC;
7. runs Basic-Auth HTTPS smoke checks against the real hosted preview;
8. automatically restores the previous preview if the hosted smoke fails.

The rollback directory is intentionally retained after PASS until the real
phone/mobile/GPS smoke is complete and U6 freezes the hosted release.

## Hosted re-check

    CALL VERIFY_AKERPASS_U5_HOSTED.bat

This is read-only and checks the hosted RC again.

## Manual real-phone gate before U6

- ÅkerVatten → VISS on real phone,
- field drawer and touch layout,
- Min position permission + correct GPS position,
- Följ mig ON/OFF while moving,
- pan/zoom behavior while follow mode is active,
- municipality/layer switching,
- Rapskartan 2025 navigation and backlink.

Only after this passes should U6 remove the rollback snapshot and formally
freeze the hosted web release.
