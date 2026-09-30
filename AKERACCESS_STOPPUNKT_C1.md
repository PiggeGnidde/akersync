# ÅkerAccess — STOPPUNKT C1 OSM last-mile path profile

C0 showed that every eligible Sjöbo field with an entry candidate was connected
through the mapped OSM graph to an ordinary-road anchor. Network connectivity
therefore adds no useful separation in this municipality beyond candidate
presence.

C1 remains descriptive and asks a more useful question: **what does the mapped
last mile look like?**

For each entry candidate C1 records the shortest mapped path to the first
ordinary-road anchor and profiles:

- mapped last-mile distance;
- track/service distance;
- OSM surface and tracktype values;
- explicit width/maxwidth;
- explicit maxheight;
- access restrictions such as private/no;
- softer access restrictions;
- barriers on the path.

The candidate entry point is projected onto its OSM way and distance to graph
nodes is measured along the way, not as a straight-line shortcut.

For field-level descriptive output C1 selects a path candidate by a temporary
lexicographic discovery rule:

1. avoid explicit access=no/private;
2. avoid explicit maxheight <4.5 m;
3. avoid explicit width/maxwidth <4.5 m;
4. shortest mapped last-mile;
5. old candidate rank as tie-break.

This rule is **not** a frozen ÅkerAccess score and is not yet an Apetit PASS/FAIL
policy. The purpose is to learn which OSM attributes have enough coverage to be
useful before bringing in NVDB.
