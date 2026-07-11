# Architecture Traceability Register

| Diagram element | Status | Repository path | Test / evidence | Capability | ADR | Notes |
|---|---|---|---|---|---|---|
| PolySia modular monolith | CURRENT | `src/polysia/`, `pyproject.toml` | `tests/migration/test_identity.py` | CAP-001–012 | ADR-0001, ADR-0002 | One Python package/process |
| CLI and safe support | CURRENT | `src/polysia/cli.py`, `src/polysia/cli_support/` | `tests/characterization/test_cli_contract.py` | CAP-011, CAP-012 | ADR-0002 | 35 commands |
| Domain models | CURRENT | `src/polysia/domain/` | `tests/architecture/test_boundaries.py` | CAP-001–010 | ADR-0002, ADR-0004 | Venue-neutral inner layer |
| Application ports | CURRENT | `src/polysia/application/ports/` | `tests/architecture/test_boundaries.py` | CAP-001–010 | ADR-0002 | Protocols exist; services are not yet populated |
| Polymarket adapter | CURRENT | `src/polysia/adapters/polymarket/` | `tests/contract/test_polymarket_sdk_surface.py` | CAP-001, CAP-008, CAP-009 | ADR-0004, ADR-0005 | SDK confined here |
| Normalized market events | CURRENT | `src/polysia/domain/events/`, `src/polysia/bus/` | `tests/integration/test_paper_vertical_slice.py` | CAP-002 | ADR-0002 | In-memory async bus |
| Decimal order book | CURRENT | `src/polysia/orderbook/` | `tests/integration/test_paper_vertical_slice.py` | CAP-003 | ADR-0001 | Snapshot/update builder |
| Microstructure features | CURRENT | `src/polysia/features/microstructure.py` | strategy unit tests | CAP-003, CAP-005 | ADR-0001 | Used by stale-price strategy |
| Strategy framework | CURRENT | `src/polysia/strategies/` | strategy unit tests | CAP-005 | ADR-0002 | Stale price and passive market maker |
| Independent risk engine | CURRENT | `src/polysia/risk/` | `tests/property/test_risk_properties.py` | CAP-006 | ADR-0008 | Final approve/reject/reduce authority |
| Kill switch | CURRENT | `src/polysia/risk/kill_switch.py` | risk and live-broker tests | CAP-006, CAP-009 | ADR-0008 | Independent emergency control |
| Paper execution | CURRENT | `src/polysia/execution/paper_broker.py` | `tests/integration/test_paper_vertical_slice.py` | CAP-007 | ADR-0001 | Conservative local fills |
| Guarded live execution | CURRENT | `src/polysia/execution/live_broker.py` | live-broker and negative-gate tests | CAP-008, CAP-009 | ADR-0007, ADR-0008, ADR-0009 | Not connected to strategy automation |
| Position and P&L | CURRENT | `src/polysia/portfolio/` | paper vertical-slice tests | CAP-007 | ADR-0001 | Operational ledger implementation |
| SQLite repositories | CURRENT | `src/polysia/storage/` | storage unit/integration tests | CAP-004 | ADR-0006 | Local/research MVP |
| Reconciliation and safety pause | CURRENT | `src/polysia/reconciliation/` | reconciliation tests and vertical slice | CAP-010 | ADR-0008 | Mismatch can pause trading |
| Monitoring and reports | CURRENT | `src/polysia/monitoring/` | monitoring golden/unit tests | CAP-011 | ADR-0009 | Sanitized operator outputs |
| Backtesting and replay | CURRENT | `src/polysia/backtesting/` | replay/backtest tests | CAP-005, CAP-007 | ADR-0009 | Paper-only execution path |
| Deployment handoff tooling | CURRENT | `src/polysia/deployment/`, `.github/workflows/ci.yml` | Phase I handoff | CAP-012 | ADR-0009, ADR-0010 | CI configured, remote run unverified |
| Strategy Registry | TARGET | — | Charter §24 | — | ADR-0002 | Identity, version, activation, suspension, retirement |
| Strategy Orchestrator | TARGET | — | Charter §24 | — | ADR-0002 | Concurrent supervision, not implemented |
| Intent Aggregator / Conflict Resolver | TARGET | — | Charter §24 | — | ADR-0002 | Resolves duplicate/correlated intents |
| Portfolio and Capital Allocator | TARGET | — | Charter §25 | — | ADR-0002 | Reserves capital before risk/execution |
| OMS / Transaction Manager | TARGET | — | Charter §29 and §59 | — | ADR-0002 | Explicit idempotency and lifecycle boundary |
| Adapter Registry | TARGET | — | Charter §32 | — | ADR-0004 | Capability discovery and routing |
| Operator Console | TARGET | — | Charter §46 | — | ADR-0008 | CLI/reports are current interface |
| Additional venue adapters | FUTURE | — | Charter §32, roadmap | — | ADR-0004 | No release commitment |
| Web3 signer and protocols | FUTURE | — | Charter §48–56 | — | ADR-0007, ADR-0008 | Separate trust boundary required |
