# Technical Debt Register

| ID | Debt | Priority | Status / next point |
|---|---|---:|---|
| TD-001 | Root CLI composition is 137 lines after responsibility decomposition and capability grouping; operations/live command modules retain broad orchestration pending explicit service and dependency-injection seams. | High | Partial; facade decomposition and grouping complete, orchestration extraction remains incremental follow-up |
| TD-002 | Core imported Polymarket adapter models. | Critical | Closed in Phase D; architecture tests enforce the boundary |
| TD-003 | Tests were concentrated under `tests/unit`. | High | Closed in Phase G; property, integration, architecture, contract, migration, and characterization layers exist |
| TD-004 | Acceptance models/renderers and manual-intervention renderers extracted; other oversized monitoring/live services remain incremental debt. | Medium | Open; extract when each service changes |
| TD-005 | Windows Conda and portable Python 3.14 pip locks exist, but the portable lock is not hash-locked. | High | Partial; add hashes before cross-platform release hardening |
| TD-006 | Historical command/report naming remains in archived evidence. | Low | Accepted; do not rewrite history |
| TD-007 | Environment variable aliases lack a formal deprecation schedule. | Medium | Open; preserve current signer/funder behavior meanwhile |
| TD-008 | Forty hidden flat CLI aliases preserve undeployed or external consumers during the namespace migration. | Medium | Open; remove only after the post-v0.2.0 owner-approved evidence gates in `docs/10-operations/cli-capability-migration.md` |
