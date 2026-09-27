# ÅkerVatten MVP v0a · STOPPUNKT F2 MarkVäta distinctness review

F passed all coverage/QA checks, but candidate MarkTorka and MarkVäta had Spearman rho = -0.924.

That is understandable because MarkTorka uses high sand + low TWI, while MarkVäta uses high clay + high TWI. Low/high TWI are exact directional opposites, and sand/clay are themselves strongly anticorrelated.

F2 therefore compares the current arithmetic 50/50 MarkVäta with joint-evidence alternatives:

- geometric mean;
- minimum;
- harmonic mean;
- two unequal arithmetic-weight diagnostics.

The joint-evidence forms make high MarkVäta require both high clay and high TWI rather than allowing one input to compensate fully for the other.

F2 also scans the soil feature schema for independent wetness-related columns such as organic soil, peat, humus, drainage, silt or soil class.

No F component is changed or frozen automatically by F2.
