# ÅkerNorm V1 discovery/reproduction

Status: discovery-only wrapper for STOPPUNKT A. This directory is not a model contract and does not freeze coefficients.

The wrapper verifies the context and validation tags, identifies the exact analysis branch/commit, verifies the imported analysis tree, validates the three frozen compact input hashes, resolves crop codes against every annual 2015–2025 dictionary, stores exact PxWeb queries and raw 2026 responses with hashes, and reruns the score-only and PTHBV climate analyses.

The final comparison is against the rounded values reported in the implementation specification. A mismatch is fatal and must not be adjusted silently.

The source cross-check preserves the exact PxWeb query, raw response and 1 kg/ha values. The imported spring-barley analysis snapshot is separately identified as a 10 kg/ha, round-half-up representation. It passes only when every non-exact cell is mathematically rounding-equivalent; every such cell is listed in the source report and summarized as a discovery warning. Any value outside that declared representation remains a fatal mismatch.

Each discovery run removes only a stale `logs/fatal_traceback.log` from an earlier attempt before starting. The independent verifier rejects a PASS manifest that still contains errors or a fatal traceback log.

Windows entry points from the feature worktree:

```cmd
py -3 -m pip install -r requirements.txt
py -3 -m pip install -r analysis\akerscore_normskord_validation_v0a\climate_requirements.txt
RUN_AKERNORM_V1_DISCOVERY.bat
VERIFY_AKERNORM_V1_REPRODUCTION.bat
```

Defaults deliberately reuse large local inputs under `C:\AkerSyncRepo\work` and `C:\AkerSyncRaw`; no large source or result file is committed.

Hard boundaries:

- no model freeze;
- no field-level production engine;
- no municipal pilot or full Skåne run;
- no web change;
- no Sentinel-2 work;
- no deployment.
