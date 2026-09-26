# Initial Traceability Matrix

| Requirement | Capability | Component | Risk control | Verification |
|---|---|---|---|---|
| REQ-001 Preserve public discovery/stream | CAP-001 | Polymarket adapter, stream | SDK boundary | Adapter and stream tests |
| REQ-002 Preserve paper vertical slice | CAP-002-007 | Domain/application/paper path, execution ledger, generic replay CLI | No live broker; fee-inclusive UTC-day Paper risk; causal market/token fee and terminal evidence or explicit unresolved status | Paper broker, Risk, replay, CLI, and integration tests |
| REQ-003 Canonical `polysia` identity | CAP-012 | Packaging and CLI | Migration inventory | Import, CLI, build tests |
| REQ-004 Prevent unauthorized live mutation | CAP-008-010 | Risk, broker, emergency control | DATA_ONLY, flags, allowlist, geoblock, acknowledgement | Negative tests and CI marker policy |
| REQ-005 Keep credentials confidential | CAP-008-012 | Config/logging/export | Ignore, redaction, staged scan | Redaction and source-export tests |
| REQ-006 Venue-neutral core | CAP-001-010 | Domain and application ports | Dependency direction | Architecture-boundary tests |
| REQ-007 Reproducible runtime | All | Packaging and locks | Exact baseline, upgrade gates | Clean-environment install and `pip check` |
| REQ-008 Stateful shadow research Replay | CAP-002-007 | Target Exposure v1, immutable SQLite Replay | No Live/Risk/Execution authority | Unit, architecture, and CLI tests |
| REQ-009 Prospective research evidence and economic evaluation | CAP-001-007 | Isolated research-evidence SQLite v2, route-local source recovery, causal depth/fee evidence, deterministic Control-vs-Target economics, bounded experiment bundles, persistent collector, public source benchmark | DATA_ONLY, no Live authority, no look-ahead, UNKNOWN stays unknown | Recovery/fault, retention/finalization, fee/depth/accounting, unit, architecture, Compose, and CLI tests |
