# Initial Traceability Matrix

| Requirement | Capability | Component | Risk control | Verification |
|---|---|---|---|---|
| REQ-001 Preserve public discovery/stream | CAP-001 | Polymarket adapter, stream | SDK boundary | Adapter and stream tests |
| REQ-002 Preserve paper vertical slice | CAP-002-007 | Domain/application/paper path | No live broker | End-to-end integration test |
| REQ-003 Canonical `polysia` identity | CAP-012 | Packaging and CLI | Migration inventory | Import, CLI, build tests |
| REQ-004 Prevent unauthorized live mutation | CAP-008-010 | Risk, broker, emergency control | DATA_ONLY, flags, allowlist, geoblock, acknowledgement | Negative tests and CI marker policy |
| REQ-005 Keep credentials confidential | CAP-008-012 | Config/logging/export | Ignore, redaction, staged scan | Redaction and source-export tests |
| REQ-006 Venue-neutral core | CAP-001-010 | Domain and application ports | Dependency direction | Architecture-boundary tests |
| REQ-007 Reproducible runtime | All | Packaging and locks | Exact baseline, upgrade gates | Clean-environment install and `pip check` |

