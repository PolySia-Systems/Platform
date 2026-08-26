# ADR-0013: Bounded Continuous Shadow Portfolio

- Status: Accepted
- Date: 2026-08-25

## Context

Stage 4A intentionally publishes immutable time windows. Operational evidence
showed that overlapping windows repeat the same trades, reset position state,
classify later sells as unknown, and let separate wallet evaluations reuse the
same visible order-book depth. Summing those windows therefore cannot produce a
valid cumulative follower P&L.

A production portfolio, generalized ledger, allocator, or execution orchestrator
would exceed current evidence and remain TARGET architecture. The immediate need
is narrower: a durable, read-only experiment that can measure forward copyability
without authorizing a trade.

## Decision

Add Stage 4B as a separate schema and application slice. Preserve Stage 4A v1.
Stage 4B owns only synthetic experimental cash, positions, attribution, fills,
fees, marks, settlement, and ledger evidence for current Stage 3 wallets.

The slice has two counterfactual layers: one portfolio per wallet and one shared
PolySia follower. A global first-seen journal and atomic watermark make replay
idempotent. The shared follower enforces capital and exposure limits and consumes
visible liquidity only once. Market-specific official fee schedules and exact
closed-market outcomes are required; missing evidence is unknown.

Lifecycle is `RUNNING -> DRAINING -> FINALIZED`. Draining blocks new exposure but
continues exits and settlement. Finalization requires zero open positions.

The application depends only on public read, candidate, lease, and local storage
ports. It has no Strategy, Risk, Execution, signing, order, cancellation, account,
or wallet-mutation port. Compose additionally forces `DATA_ONLY` and Live false.

Schema v4, dated 2026-08-26, keeps the mixed FOLLOWER portfolio as the labeled
baseline, adds independent Alpha and Stress followers that start empty on
migration, persists CLOSE/SETTLEMENT attribution, records mark source age, and
runs a persistent fenced worker. Report-time walk-forward filters do not replace
the baseline fill policy.

## Consequences

Continuous cumulative P&L becomes auditable across polls and restarts. Alpha and
Stress can be compared without treating repeated windows as new trades. Failures
retain the last known good portfolio and watermark.

The model remains a simulation. Public API latency, polling, book snapshots, and
synthetic capital differ from real execution. A successful experiment is evidence
for later research, not profitability, production readiness, or Live authorization.

The additional normalized tables increase the protected database and backup size.
The persistent worker removes one-shot container start cost; public reads remain
bounded by the existing rate scheduler and telemetry.

## Alternatives rejected

- Summing Stage 4A windows: duplicates trades and loses cross-window inventory.
- Editing Stage 4A in place: would invalidate existing evidence and rollback.
- Reusing one fixed wallet file: loses dynamic Stage 3 provenance and retained exits.
- Building a generalized OMS/portfolio platform now: speculative and disproportionate.
- Assuming a flat fee: contradicted by current official per-market fee schedules.

## Validation and rollback

Validation covers Decimal fee/accounting functions, shared-depth properties,
first-seen dedupe, persistent cross-run exits, settlement, failure recovery,
schema idempotency, Stage 4A compatibility, address-free output, CLI safety,
backup/restore, container configuration, and restart behavior.

Rollback disables `polysia-wallet-intelligence-shadow-portfolio.service`,
restores the prior immutable application release and pre-migration backup, and
re-enables the optional oneshot timer only when rolling back to a schema-v3
image. Stage 4A and Stages 1–3 continue independently.
