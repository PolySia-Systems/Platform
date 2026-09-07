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
  fixes, exact Standards v0.4.0 enforcement, and repository identity cleanup.
- Bounded control: a SHADOW-only Control Kernel for `stale-price@0.1.0` with
  immutable desired-state revisions, optimistic concurrency, idempotency,
  observed state, and audit history.
- Tiny Live Copy run four: one accepted unfilled Post-only order, terminal
  `FAILED_SAFE` on ambiguous immediate cancellation confirmation, and later
  verified zero open orders, fills, exposure, and experiment cost.
- Cancellation safety closure: a durable venue-neutral finality gate with one
  possible cancel send, restart-safe no-resend behavior, fully paginated open
  orders, explicit outcomes, consecutive clean observations, and independent
  order-detail, linked-trade, and position evidence. Pinned SDK 0.7.1 contract
  fixtures cover order aliases, Decimal fields, and mixed cancel results.
- Data-only Wallet Intelligence: protected PolyCop ingestion plus canonical
  multi-source wallet identity, source-derived time-safe features, independent
  readiness, versioned candidate policy, deterministic ranking, persistent
  lease fencing, atomic address-free publication, copyability Alpha/Stress
  selection, dynamic official Polymarket trade evidence, versioned Historical
  cost modeling, current-book Forward Shadow, and last-known-good recovery.
- Stage 4B accounting hardening: one authoritative invariant evaluator, an
  in-transaction publication gate, failed evidence, unchanged watermark on
  failure, and controlled `accounting_blocked` shutdown without restart loops.
- Live boundary hardening: unknown is distinct from measured zero, verified
  state is distinct from assumptions, generic limit-order submission is
  preview-only, and market execution sends exactly the immutable request
  approved by Risk.

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

1. Operate the persistent prospective collector on the authorized Helsinki
   DATA_ONLY host. Do not access Nuremberg. The immutable local Helsinki-final
   backup remains the historical source of truth for Replay.
2. Keep Target Exposure v1 as the only primary Challenger until its PARTIAL
   coverage and UNKNOWN marks are honestly classified. Do not add exploratory
   strategy contests.
3. Public source benchmark and persistent prospective collector are implemented
   as DATA_ONLY research. Next: observe the rolling ten-minute windows, then
   Structural Scanner / Placebo work only if evidence supports it.
4. Acquire additional reproducible BTC Up/Down historical data only when a new
   question cannot be answered from the frozen backup.
5. Consider a separately authorized Tiny-Live sample only after safety and
   evidence-based promotion gates pass. Do not scale capital from LIVE-004.

## Parallel maintenance gates

- Keep Python 3.14.7, `polymarket-client==0.7.1`, Mypy 2.3.1, and Ruff 0.16.6
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
