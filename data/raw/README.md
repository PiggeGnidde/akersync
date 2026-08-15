# Raw data

Rådata ligger INTE i Git-repot.

`SETUP_PATHS.bat` pekar i stället ut var filerna redan finns på datorn.

För v0.92 krävs:
- Jordbruksverket `arslager_block.gpkg`
- Jordbruksverket `arslager_skifte.gpkg`
- SLU/DSMS `akermarkens-jordarter.zip`
- Lantmäteriet Markhöjdmodell-mapp med de relevanta `.tif`-rutorna
  (vår nuvarande build: 231 landrutor)

`FREEZE_INPUTS_SHA256.bat` skapar `qa/input_manifest.json` med checksummor.
