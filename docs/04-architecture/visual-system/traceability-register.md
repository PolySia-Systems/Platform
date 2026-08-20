# Architecture Traceability Register

| Diagram element | Status | Repository path | Test / evidence | Capability | ADR | Notes |
|---|---|---|---|---|---|---|
| PolySia modular monolith | CURRENT | `src/polysia/`, `pyproject.toml` | `tests/contract/test_distribution_identity.py`, `tests/architecture/test_boundaries.py` | CAP-001–012 | ADR-0001, ADR-0002 | One Python distribution and deployable modular monolith |
| CLI commands and safe support | CURRENT | `src/polysia/cli.py`, `src/polysia/cli_commands/`, `src/polysia/cli_support/` | `tests/contract/test_cli_surface.py`, `tests/unit/cli/` | CAP-011, CAP-012 | ADR-0002 | Composition-only facade with a contract-tested flat 41-name inventory, including the bounded `control` group |
| Domain models | CURRENT | `src/polysia/domain/` | `tests/unit/domain/test_models.py`, `tests/architecture/test_boundaries.py` | CAP-001–010 | ADR-0002, ADR-0004 | Venue-neutral inner layer |
| Application ports | CURRENT | `src/polysia/application/ports/` | `tests/architecture/test_boundaries.py` | CAP-001–010 | ADR-0002 | Protocols exist; services are not yet populated |
| Polymarket adapter | CURRENT | `src/polysia/adapters/polymarket/` | `tests/contract/test_polymarket_sdk_surface.py`, `tests/unit/adapters/` | CAP-001, CAP-008, CAP-009 | ADR-0004, ADR-0011 | SDK confined here |
| Normalized market events | CURRENT | `src/polysia/domain/events/`, `src/polysia/bus/` | `tests/integration/test_paper_vertical_slice.py`, `tests/unit/bus/test_in_memory_bus.py` | CAP-002 | ADR-0002 | In-memory async bus |
| Decimal order book | CURRENT | `src/polysia/orderbook/` | `tests/unit/orderbook/`, `tests/integration/test_paper_vertical_slice.py` | CAP-003 | ADR-0001 | Snapshot/update builder |
| Microstructure features | CURRENT | `src/polysia/features/microstructure.py` | `tests/unit/features/test_microstructure.py` | CAP-003, CAP-005 | ADR-0001 | Used by research strategies |
| Strategy framework | CURRENT | `src/polysia/strategies/` | `tests/unit/strategies/` | CAP-005 | ADR-0002 | Includes research strategies and the bounded BTC 15-minute Copy strategy |
| Independent risk engine | CURRENT | `src/polysia/risk/` | `tests/property/test_risk_properties.py`, `tests/unit/risk/` | CAP-006 | ADR-0008 | Final approve/reject/reduce authority |
| Kill switch | CURRENT | `src/polysia/risk/kill_switch.py` | `tests/unit/risk/test_kill_switch.py`, `tests/unit/execution/test_live_broker.py` | CAP-006, CAP-009 | ADR-0008 | Independent emergency control |
| Paper execution | CURRENT | `src/polysia/execution/paper_broker.py` | `tests/integration/test_paper_vertical_slice.py`, `tests/unit/execution/test_paper_broker.py` | CAP-007 | ADR-0001 | Conservative local fills |
| Guarded live execution | CURRENT | `src/polysia/execution/live_broker.py` | `tests/unit/execution/test_live_broker.py`, `tests/integration/test_tiny_live_round_trip_vertical_slice.py` | CAP-008, CAP-009 | ADR-0007, ADR-0008, ADR-0009 | No general automated strategy-to-Live connection |
| Position and P&L | CURRENT | `src/polysia/portfolio/` | `tests/unit/portfolio/test_pnl.py`, `tests/integration/test_paper_vertical_slice.py` | CAP-007 | ADR-0001 | Operational ledger implementation |
| SQLite repositories | CURRENT | `src/polysia/storage/` | `tests/unit/storage/`, `tests/integration/test_shadow_control_vertical_slice.py` | CAP-004 | ADR-0006 | Local/research and current single-runtime persistence |
| Reconciliation and safety pause | CURRENT | `src/polysia/reconciliation/` | `tests/unit/reconciliation/`, `tests/integration/test_tiny_live_round_trip_vertical_slice.py` | CAP-010 | ADR-0008 | Mismatch can pause trading |
| Monitoring and reports | CURRENT | `src/polysia/monitoring/` | `tests/unit/monitoring/` | CAP-011 | ADR-0009 | Sanitized operator outputs |
| Backtesting and replay | CURRENT | `src/polysia/backtesting/` | `tests/unit/backtesting/` | CAP-005, CAP-007 | ADR-0009 | Paper-only execution path |
| Deployment and CI tooling | CURRENT | `src/polysia/deployment/`, `.github/workflows/ci.yml`, `Dockerfile`, `compose.yaml` | `tests/unit/deployment/`, `docs/18-ai-handoffs/polysia-controlled-server-deployment-handoff.md` | CAP-012 | ADR-0009, ADR-0010, ADR-0011 | Current CI is remotely verified; deployed runtime has a separately recorded older baseline |
| Strategy Registry | CURRENT | `src/polysia/domain/strategy/`, `src/polysia/storage/repositories.py`, `src/polysia/storage/schemas.sql` | `tests/unit/strategies/test_registry.py`, `tests/unit/storage/test_repositories.py` | CAP-005 | ADR-0002, ADR-0012 | Bounded identity, version, lifecycle, run evidence, and unrated performance; no orchestration |
| SHADOW-only Control Kernel | CURRENT | `src/polysia/control/`, `src/polysia/storage/control.py`, `src/polysia/monitoring/shadow_run.py` | `tests/integration/test_shadow_control_vertical_slice.py`, `tests/unit/control/`, `tests/architecture/test_boundaries.py` | CAP-005, CAP-011 | ADR-0012 | `stale-price@0.1.0` `RUNNING`/`PAUSED` only; no PAPER, LIVE, Web, API, or AI authority |
| Bounded Tiny Live Copy experiment | CURRENT | `src/polysia/domain/copytrading/`, `src/polysia/execution/tiny_live_copy.py`, `src/polysia/storage/copytrading.py` | `tests/integration/test_tiny_live_copy_vertical_slice.py`, `tests/unit/execution/test_tiny_live_copy_safety.py`, `docs/18-ai-handoffs/polysia-tiny-live-copy-004-cancellation-diagnostic.md` | CAP-005, CAP-008, CAP-009, CAP-010 | ADR-0007, ADR-0008 | Experimental owner-bounded path; run four ended `FAILED_SAFE` with zero confirmed fill, exposure, and cost |
| Strategy Orchestrator | TARGET | — | Charter §24 | — | ADR-0002 | Concurrent supervision, not implemented |
| Intent Aggregator / Conflict Resolver | TARGET | — | Charter §24 | — | ADR-0002 | Resolves duplicate/correlated intents |
| Portfolio and Capital Allocator | TARGET | — | Charter §25 | — | ADR-0002 | Reserves capital before risk/execution |
| OMS / Transaction Manager | TARGET | — | Charter §29 and §59 | — | ADR-0002 | Explicit idempotency and lifecycle boundary |
| Adapter Registry | TARGET | — | Charter §32 | — | ADR-0004 | Capability discovery and routing |
| Operator Console | TARGET | — | Charter §46 | — | ADR-0008 | CLI/reports are current interface |
| Additional venue adapters | FUTURE | — | Charter §32, roadmap | — | ADR-0004 | No release commitment |
| Web3 signer and protocols | FUTURE | — | Charter §48–56 | — | ADR-0007, ADR-0008 | Separate trust boundary required |
