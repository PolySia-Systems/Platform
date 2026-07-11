# Technical Debt Register

| ID | Debt | Priority | Planned phase |
|---|---|---:|---|
| TD-001 | CLI reduced from 2,866 to 2,582 lines; command-group wiring remains concentrated pending dependency-injection conversion. | High | F follow-up |
| TD-002 | Core imports Polymarket adapter models. | Critical | D |
| TD-003 | Tests concentrated under `tests/unit`. | High | G |
| TD-004 | Acceptance models/renderers and manual-intervention renderers extracted; other oversized monitoring/live services remain incremental debt. | Medium | F follow-up |
| TD-005 | No portable application lock or CI matrix yet. | High | G |
| TD-006 | Historical command/report naming remains in archived evidence. | Low | Archive only; do not rewrite history. |
| TD-007 | Environment variable aliases lack a formal migration layer. | Medium | C/D |
