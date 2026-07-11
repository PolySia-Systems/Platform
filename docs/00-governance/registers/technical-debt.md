# Technical Debt Register

| ID | Debt | Priority | Status / next point |
|---|---|---:|---|
| TD-001 | CLI reduced from 2,866 to 2,582 lines; command-group wiring remains concentrated pending dependency-injection conversion. | High | Open; incremental follow-up |
| TD-002 | Core imported Polymarket adapter models. | Critical | Closed in Phase D; architecture tests enforce the boundary |
| TD-003 | Tests were concentrated under `tests/unit`. | High | Closed in Phase G; property, integration, architecture, contract, migration, and characterization layers exist |
| TD-004 | Acceptance models/renderers and manual-intervention renderers extracted; other oversized monitoring/live services remain incremental debt. | Medium | Open; extract when each service changes |
| TD-005 | Windows application lock exists and CI covers Python 3.11/3.13, but no portable hash-locked resolution exists. | High | Partial; complete before cross-platform release |
| TD-006 | Historical command/report naming remains in archived evidence. | Low | Accepted; do not rewrite history |
| TD-007 | Environment variable aliases lack a formal deprecation schedule. | Medium | Open; preserve current signer/funder behavior meanwhile |
