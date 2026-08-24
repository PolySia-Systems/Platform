# PolySia Roadmap

## Delivered foundation

- Repository modernization: migration baseline, governance, canonical identity,
  venue-neutral boundaries, Polymarket adapter, modular-monolith decomposition,
  testing/CI/supply-chain controls, controlled validation, and delivery.
- Limited-live slice: minimum-size FAK entry, actual-fill-sized GTC exit,
  persistent one-attempt authorization, and complete local execution evidence.
- Runtime closure: delayed-fill reconciliation, idempotent ledger/P&L updates,
  bounded lifecycle monitoring, fee-aware target calculation, structured
  adapter diagnostics, server-clock preflight, runtime configuration reporting,
  bounded read retry, and verified recovery backup.
- Platform maintenance: Python 3.14-only CI optimization, dependency security
  fixes, exact Standards v0.1.1 enforcement, and repository identity cleanup.
- Bounded control: a SHADOW-only Control Kernel for `stale-price@0.1.0` with
  immutable desired-state revisions, optimistic concurrency, idempotency,
  observed state, and audit history.
- Tiny Live Copy run four: one accepted unfilled Post-only order, terminal
  `FAILED_SAFE` on ambiguous immediate cancellation confirmation, and later
  verified zero open orders, fills, exposure, and experiment cost.
- Cancellation safety closure: a durable venue-neutral finality gate with one
  possible cancel send, restart-safe no-resend behavior, fully paginated open
  orders, explicit outcomes, consecutive clean observations, and independent
  order-detail, linked-trade, and position evidence. SDK 0.6.0 wire fixtures
  cover order aliases, Decimal fields, and mixed cancel results.
- Data-only Wallet Intelligence: protected PolyCop ingestion plus canonical
  multi-source wallet identity, source-derived time-safe features, independent
  readiness, versioned candidate policy, deterministic ranking, persistent
  lease fencing, atomic address-free publication, copyability Alpha/Stress
  selection, dynamic official Polymarket trade evidence, versioned Historical
  cost modeling, current-book Forward Shadow, and last-known-good recovery.

## Completed safety maintenance gate

The bounded cancellation-confirmation and terminal order-response repair is
implemented and deterministically tested without credentials, network access,
Live mutation, deployment, or changes to retained historical run evidence.
Operational promotion remains a separate authorization and deployment task.

## Completed data-only operational gate

Wallet Intelligence Stages 1–4 are deployed on the controlled Helsinki host
without trading authority. First-start reuse, daily scheduling, natural
ten-minute Forward execution, Historical modeling, rate telemetry, dynamic
handoff, authenticated one-cycle dry-run, backup/restore, and rollback assets
were verified. `LIVE_TRADING_ENABLED=false`; Live review and authorization
remain separate promotion stages.

## Immediate next cycle: research and validation

1. Observe multiple scheduled DATA_ONLY/Shadow cycles, establish external alert
   delivery and encrypted off-host backup, and quantify source/data stability.
2. Acquire and validate reproducible BTC Up/Down 15-minute historical data,
   including market metadata, outcomes, book/liquidity snapshots, fee schedules,
   and timestamps.
   Any external research-data provider must remain read-only, pass a bounded
   preflight, use outcome-token identifiers for books, and classify
   incomplete order-book data as non-promotable research evidence.
3. Define naive and market-aware benchmarks plus data-quality, leakage,
   slippage, liquidity, and fee assumptions before strategy evaluation.
4. Run realistic out-of-sample backtests and report net P&L, drawdown,
   calibration, turnover, execution feasibility, and regime sensitivity.
5. Run a large Paper/Shadow sample using the same accounting and promotion
   metrics.
6. Consider a separately authorized Tiny-Live sample only after the safety
   maintenance gate and evidence-based promotion gates pass. Do not scale
   capital from the single profitable LIVE-004 result.

## Parallel maintenance gates

- Keep Python 3.14.6, `polymarket-client==0.6.0`, Mypy 2.3.0, and Ruff 0.16.4
  pinned until new contract, lock, security, and rollback evidence approves an
  upgrade.
- Preserve the legacy project, database, live evidence, and verified recovery
  package until a separate owner-approved retirement task. Current `main`
  supports only Python 3.14; older runtime support requires a deliberate
  compatibility rollback.
- Add branch protection and portable cross-platform locking only through a
  focused governance/release-hardening task.
- Keep architecture Mermaid sources, views, SVGs, index metadata, and
  traceability synchronized through the lightweight documentation validator and
  human semantic/visual review.

## Explicitly deferred

New strategies, additional venues, Web3/DeFi expansion, generalized or
permanent Copy Trading, AI/ML, cloud deployment, microservices, Kubernetes,
operator web UI, generalized OMS, multi-strategy capital allocation, and
capital scaling are not immediate work.
