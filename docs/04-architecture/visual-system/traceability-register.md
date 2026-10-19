# Architecture Traceability Register

| Diagram element | Status | Repository path | Test / evidence | Capability | ADR | Notes |
|---|---|---|---|---|---|---|
| PolySia modular monolith | CURRENT | `src/polysia/`, `pyproject.toml` | `tests/contract/test_distribution_identity.py`, `tests/architecture/test_boundaries.py` | CAP-001–012 | ADR-0001, ADR-0002 | One Python distribution and deployable modular monolith |
| CLI commands and safe support | CURRENT | `src/polysia/cli.py`, `src/polysia/cli_commands/`, `src/polysia/cli_support/` | `tests/contract/test_cli_surface.py`, `tests/unit/cli/` | CAP-011, CAP-012 | ADR-0002 | Composition-only facade with six capability namespaces, 40 hidden compatibility aliases, and an unchanged bounded `control` group |
| Domain models | CURRENT | `src/polysia/domain/` | `tests/unit/domain/test_models.py`, `tests/architecture/test_boundaries.py` | CAP-001–010 | ADR-0002, ADR-0004 | Venue-neutral inner layer |
| Application ports | CURRENT | `src/polysia/application/ports/` | `tests/architecture/test_boundaries.py` | CAP-001–010 | ADR-0002 | Protocol boundaries used by current Wallet Intelligence services |
| Application services | CURRENT | `src/polysia/application/services/` | `tests/unit/application/test_candidate_intelligence.py`, `tests/unit/application/test_dynamic_shadow_service.py`, `tests/integration/test_continuous_shadow_portfolio.py` | CAP-004, CAP-005, CAP-011 | ADR-0002 | Wallet ingestion, candidate intelligence, copyability selection, dynamic and continuous Shadow, and protected handoff orchestration |
| Polymarket adapter | CURRENT | `src/polysia/adapters/polymarket/` | `tests/contract/test_polymarket_sdk_surface.py`, `tests/unit/adapters/` | CAP-001, CAP-008, CAP-009 | ADR-0004, ADR-0011 | SDK confined here |
| Normalized market events | CURRENT | `src/polysia/domain/events/`, `src/polysia/bus/` | `tests/integration/test_paper_vertical_slice.py`, `tests/unit/bus/test_in_memory_bus.py` | CAP-002 | ADR-0002 | In-memory async bus |
| Decimal order book | CURRENT | `src/polysia/orderbook/` | `tests/unit/orderbook/`, `tests/integration/test_paper_vertical_slice.py` | CAP-003 | ADR-0001 | Snapshot/update builder |
| Microstructure features | CURRENT | `src/polysia/features/microstructure.py` | `tests/unit/features/test_microstructure.py` | CAP-003, CAP-005 | ADR-0001 | Used by research strategies |
| Strategy framework | CURRENT | `src/polysia/strategies/` | `tests/unit/strategies/` | CAP-005 | ADR-0002 | Includes research strategies and the bounded BTC 15-minute Copy strategy |
| Independent risk engine | CURRENT | `src/polysia/risk/` | `tests/property/test_risk_properties.py`, `tests/unit/risk/` | CAP-006 | ADR-0008, ADR-0016 | Final approve/reject/reduce authority; UNKNOWN or assumed Live state cannot authorize submission |
| Kill switch | CURRENT | `src/polysia/risk/kill_switch.py` | `tests/unit/risk/test_kill_switch.py`, `tests/unit/execution/test_live_broker.py` | CAP-006, CAP-009 | ADR-0008 | Independent emergency control |
| Paper execution | CURRENT | `src/polysia/execution/paper_broker.py` | `tests/integration/test_paper_vertical_slice.py`, `tests/unit/execution/test_paper_broker.py` | CAP-007 | ADR-0001 | Conservative local fills |
| Guarded live execution | CURRENT | `src/polysia/execution/live_broker.py`, `src/polysia/execution/canonical_order.py`, `src/polysia/execution/verified_live_state.py`, `src/polysia/risk/evidence.py` | `tests/unit/execution/test_live_broker.py`, `tests/unit/risk/test_verified_live.py`, `tests/integration/test_tiny_live_round_trip_vertical_slice.py` | CAP-008, CAP-009 | ADR-0007, ADR-0008, ADR-0009, ADR-0016 | Verified read-only Live state is required; Execution submits the exact immutable Risk-approved request; generic limit-order Live remains preview-only |
| Position and P&L | CURRENT | `src/polysia/portfolio/` | `tests/unit/portfolio/test_pnl.py`, `tests/integration/test_paper_vertical_slice.py` | CAP-007 | ADR-0001 | Operational ledger implementation |
| SQLite repositories | CURRENT | `src/polysia/storage/`, `src/polysia/storage/continuous_shadow_invariants.py` | `tests/unit/storage/`, `tests/integration/test_shadow_control_vertical_slice.py`, `tests/integration/test_continuous_shadow_portfolio.py` | CAP-004 | ADR-0006, ADR-0014, ADR-0015 | Local/research and current single-runtime persistence; Stage 4B current valuation is mutable, mark history is bounded, and failed accounting/publication invariants cannot commit or advance progress |
| Prospective economic evaluation | CURRENT | `src/polysia/domain/research_evidence/`, `src/polysia/backtesting/prospective_replay.py`, `src/polysia/backtesting/prospective_economics.py`, `src/polysia/backtesting/offline_research_lab.py`, `src/polysia/deployment/research_experiment_runner.py`, `src/polysia/adapters/polymarket/research_sources.py` | `tests/unit/domain/research_evidence/`, `tests/unit/backtesting/test_prospective_economics.py`, `tests/unit/adapters/test_polymarket_research_sources.py`, `tests/integration/test_offline_research_lab.py`, `tests/integration/test_research_experiment_runner.py` | CAP-001-007 | ADR-0017 | Research-only causal depth/fee evidence, deterministic Control-vs-Target economics, read-only bundle analysis, an offline production-path laboratory, and a bounded resumable Runner; DATA_ONLY and no Live authority |
| Reconciliation and safety pause | CURRENT | `src/polysia/reconciliation/` | `tests/unit/reconciliation/`, `tests/integration/test_tiny_live_round_trip_vertical_slice.py` | CAP-010 | ADR-0008 | Mismatch can pause trading |
| Monitoring and reports | CURRENT | `src/polysia/monitoring/` | `tests/unit/monitoring/` | CAP-011 | ADR-0009 | Sanitized operator outputs |
| Backtesting and replay | CURRENT | `src/polysia/backtesting/` | `tests/unit/backtesting/` | CAP-005, CAP-007 | ADR-0009 | Paper-only execution path |
| Deployment and CI tooling | CURRENT | `src/polysia/deployment/`, `.github/workflows/ci.yml`, `Dockerfile`, `compose.yaml` | `tests/unit/deployment/`, `docs/18-ai-handoffs/polysia-controlled-server-deployment-handoff.md` | CAP-012 | ADR-0009, ADR-0010, ADR-0011 | Current CI is remotely verified; deployed runtime has a separately recorded older baseline |
| Historical Wallet Intelligence deployment topology | CURRENT | `deploy/systemd/`, `compose.yaml` | `docs/18-ai-handoffs/stage4b-data-lifecycle-v1.md`, `docs/18-ai-handoffs/stage4b-data-ownership-cutover.md` | CAP-004, CAP-011 | ADR-0014, ADR-0015 | Historical implementation topology only; actual activity requires dated runtime evidence; separate physical stores remain supported |
| Strategy Registry | CURRENT | `src/polysia/domain/strategy/`, `src/polysia/storage/repositories.py`, `src/polysia/storage/schemas.sql` | `tests/unit/strategies/test_registry.py`, `tests/unit/storage/test_repositories.py` | CAP-005 | ADR-0002, ADR-0012 | Bounded identity, version, lifecycle, run evidence, and unrated performance; no orchestration |
| SHADOW-only Control Kernel | CURRENT | `src/polysia/control/`, `src/polysia/storage/control.py`, `src/polysia/monitoring/shadow_run.py` | `tests/integration/test_shadow_control_vertical_slice.py`, `tests/unit/control/`, `tests/architecture/test_boundaries.py` | CAP-005, CAP-011 | ADR-0012 | `stale-price@0.1.0` `RUNNING`/`PAUSED` only; no PAPER, LIVE, Web, API, or AI authority |
| Bounded Tiny Live Copy experiment | CURRENT | `src/polysia/domain/copytrading/`, `src/polysia/execution/tiny_live_copy.py`, `src/polysia/storage/copytrading.py` | `tests/integration/test_tiny_live_copy_vertical_slice.py`, `tests/unit/execution/test_tiny_live_copy_safety.py`, `docs/18-ai-handoffs/polysia-tiny-live-copy-004-cancellation-diagnostic.md` | CAP-005, CAP-008, CAP-009, CAP-010 | ADR-0007, ADR-0008 | Experimental owner-bounded path; run four ended `FAILED_SAFE` with zero confirmed fill, exposure, and cost |
| Strategy Orchestrator | TARGET | — | Charter §24 | — | ADR-0002 | Concurrent supervision, not implemented |
| Intent Aggregator / Conflict Resolver | TARGET | — | Charter §24 | — | ADR-0002 | Resolves duplicate/correlated intents |
| Portfolio and Capital Allocator | TARGET | — | Charter §25 | — | ADR-0002 | Reserves capital before risk/execution |
| OMS / Transaction Manager | TARGET | — | Charter §29 and §59 | — | ADR-0002 | Explicit idempotency and lifecycle boundary |
| Adapter Registry | TARGET | — | Charter §32 | — | ADR-0004 | Capability discovery and routing |
| Private research Console | CURRENT | `src/polysia/monitoring/console.py` | `tests/browser/test_console_browser.py`, `tests/unit/monitoring/test_console.py` | CAP-011 | ADR-0021 | Bounded retained-data UI; deployment and owner comprehension are separate receipts |
| Generalized execution Console | TARGET | — | Charter §46 | — | ADR-0008 | No generalized control or Live authority |
| Additional venue adapters | FUTURE | — | Charter §32, roadmap | — | ADR-0004 | No release commitment |
| Web3 signer and protocols | FUTURE | — | Charter §48–56 | — | ADR-0007, ADR-0008 | Separate trust boundary required |

Independent Platform deployment, durable authority and encrypted recovery are
traced by `deploy/platform_bootstrap.py`, `deploy/platform_backup.py`,
`tests/unit/storage/test_acquisition_authority.py` and the dated
`docs/18-ai-handoffs/platform-independent-shadow-2026-10-16.md` execution record.

Scoped review 2026-10-19 against `4f3b611adae17defbcc6e24b4f9f917b466d5ad8`:
views 13/15 trace private gateway identity, protected Unix socket, isolated browser
trust, durable OS restart fencing and independent SFTP/age recovery to
`deploy/platform_admin.py`, `src/polysia/deployment/gateway.py`, exact-main
CI 39274691513 and the appended clean-install receipt in the execution record.
Fresh UNCONFIGURED state is not a campaign, authority grant or financial result.
