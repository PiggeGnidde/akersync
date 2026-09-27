# ÅkerVatten MVP v0a · STOPPUNKT B2 NADIA validation

The core B pilot proved 100/100 spatial linkage through:

`field -> SVAR2022 Delavrinningsområden ARO_UUID -> Vattenwebb Aroid -> Subid`.

The remaining B2 check deliberately uses SMHI's documented NADIA user interface instead of reverse-engineering an undocumented backend.

Open:

https://vattenwebb.smhi.se/nadia/

Paste the five SUBIDs printed by the B pilot as a comma-separated list.

Choose:

- Modelldata
- Delavrinningsområden: the five SUBIDs
- Tidssteg: dygn
- Från år: 2025
- Till och med år: 2025

Download the official file, then run:

    CALL RUN_AKERVATTEN_B2_NADIA_VALIDATE.bat "C:\path\to\downloaded_file.xls"

The validator requires:

- all five requested SUBIDs to occur in the official output;
- at least one sheet with a credible daily time axis (>=30 detected dates);
- numeric time-series content.

No hidden/private endpoint is called by the validator.
