# ÅkerAccess D6a — Slitlager / paved public-road check

Triggered by visual QA of field `62263103013|20A` near Manhemsvägen/Horsarydsvägen.

The current web metric "Till statlig/kommunal väg" is administrative: it only
uses NVDB Väghållare and therefore does not imply asphalt, width or truck
suitability.

D6a adds NVDB **Slitlager** and computes a new candidate feature:

`nearest_belagd_statlig_kommunal_nvdb_m`

Method:

1. fetch/cache Slitlager once for the frozen D0 Skåne bbox,
2. select Slitlagertyp=Belagd,
3. link paved Slitlager segments to statlig/kommunal Väghållare geometry using
   a tight 2 m midpoint tolerance on the common NVDB network,
4. compute field-polygon distance to the nearest such segment,
5. print exact Väghållare + Slitlager values for the QA field.

D6a deliberately does **not** change BestMatch ranking or the production web
metric yet. First inspect whether NVDB Slitlager actually resolves the observed
Manhemsvägen case. This avoids promoting another proxy before falsification.

Run:

`CALL RUN_AKERACCESS_D6A_SURFACE_CHECK.bat`
