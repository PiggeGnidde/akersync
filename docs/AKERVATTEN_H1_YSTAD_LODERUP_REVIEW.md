# ÅkerVatten H1 · Ystad / Löderup hydrology review

H1 is a focused diagnostic after H0.

It compares three points:

1. the Ystad field with frozen **GrundvattenTillgång minimum**;
2. the Ystad field with frozen **GrundvattenTorka maximum**;
3. the public address coordinate for **Löderups Växt AB, Norra Strandbadsvägen 134**.

The Löderup point is an address reference only. H1 does not assert that the nearest field belongs to or is farmed by Löderups Växt.

## Questions

For each focus point H1 asks:

- Which SGU large groundwater magazine(s) contain the point?
- Which unique magazine IDs and vertical J/S/K positions apply?
- Which SGU magazine subarea(s) apply?
- Which withdrawal-opportunity class is attached to each subarea?
- Does the point lie in a mapped recharge area?
- Which SGU-HYPE groundwater unit (`omrade_id`) contains it?
- Which SVAR2022 subcatchment (`ARO_UUID`) contains it?
- Which S-HYPE `Subid` corresponds to that catchment?
- Are the three points actually in the same or different hydrological units?

## Map-ready outputs

H1 exports GeoJSON for:

- focus points;
- matching SGU groundwater magazines;
- matching magazine subareas;
- matching recharge areas;
- matching SGU-HYPE groundwater units;
- matching SVAR2022 catchments.

These are intended for direct visual inspection of the Fårarp/Ystad/Löderup hypothesis.

## Important semantics

A mapped SGU withdrawal class is hydrogeological screening information.

It is not:

- a legal withdrawal right;
- a vattendom;
- a guaranteed well flow;
- proof that a new agricultural irrigation abstraction can be permitted.

No ÅkerVatten score is changed or created in H1.
