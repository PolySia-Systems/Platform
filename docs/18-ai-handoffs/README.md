# Current Evidence Index

This is the canonical index for current repository, safety, operational, and
delivery evidence selected by the Master Operating Charter. Historical records
remain evidence, not current operating instructions.

The immutable baseline remains at
[`docs/13-ai-handoffs/BASELINE_AUDIT.md`](../13-ai-handoffs/BASELINE_AUDIT.md)
because that exact path is an immutable compliance artifact.

## Repository truth

- [`cs-lease-recovery-telemetry-isolation.md`](cs-lease-recovery-telemetry-isolation.md)
  records stable Continuous Shadow lease ownership, process-local poll
  exclusion, and physical isolation of latency telemetry SQLite.
- [`latency-performance-intelligence-v0-1.md`](latency-performance-intelligence-v0-1.md)
  records the observational latency contract, bounded SQLite telemetry, and
  pending 24-hour Helsinki real-data gate.
- [`wallet-intelligence-stage4b-v4-reliability.md`](wallet-intelligence-stage4b-v4-reliability.md)
  records schema v4 attribution, Alpha/Stress isolation, persistent DATA_ONLY
  worker, and the remaining Finland deploy steps. The prior
  [`wallet-intelligence-stage4b-continuous-shadow.md`](wallet-intelligence-stage4b-continuous-shadow.md)
  remains the last verified Helsinki schema-v3 runtime evidence.
- [`wallet-intelligence-stage4-dynamic-shadow.md`](wallet-intelligence-stage4-dynamic-shadow.md)
  records the dynamic Alpha/Stress consumer, official all-market Polymarket
  reads, modeled Historical evaluation, current-book Forward Shadow, and
  no-order boundary.
- [`wallet-intelligence-stage3.md`](wallet-intelligence-stage3.md) records the
  versioned Alpha, Stress, Watchlist, Rejected, and empty Live-review selection
  pools.
- [`wallet-intelligence-stage2.md`](wallet-intelligence-stage2.md) records the
  canonical identity, source-derived features, readiness, versioned candidate
  policy, deterministic ranking, fenced publication, and final read-only smoke.
- [`polycop-candidate-wallet-ingestion.md`](polycop-candidate-wallet-ingestion.md)
  records the protected Stage 1 PolyCop ingestion, history, health, and
  backup/restore foundation.
- [`architecture-truth-refresh-2026-08-18.md`](architecture-truth-refresh-2026-08-18.md)
  records the repository-wide architecture audit, refreshed visual baseline,
  and automated drift prevention.
- [`polysia-upgrade-006-handoff.md`](polysia-upgrade-006-handoff.md) records the
  Python 3.14, dependency, SDK, reproducibility, and security baseline.
- [`polysia-phase-closure-005-final-handoff.md`](polysia-phase-closure-005-final-handoff.md)
  and its JSON companion record the latest completed engineering closure.

## Current safety and operational evidence

- [`polysia-finland-wallet-intelligence-deployment.md`](polysia-finland-wallet-intelligence-deployment.md)
  records the current Helsinki DATA_ONLY Stages 1–4 deployment, dynamic
  pre-Live handoff, authenticated no-mutation dry-run, backup/restore, rollback,
  and `3x-ui` preservation evidence.
- [`polysia-tiny-live-copy-004-cancellation-diagnostic.md`](polysia-tiny-live-copy-004-cancellation-diagnostic.md)
  records the accepted unfilled Post-only order, fail-safe cancellation
  ambiguity, and later proof of a flat account with zero experiment cost.
- [`polysia-post-only-final-recheck.md`](polysia-post-only-final-recheck.md)
  records the TOCTOU diagnosis, final order-book recheck, and explicit
  submission outcome model.
- [`polysia-controlled-server-deployment-handoff.md`](polysia-controlled-server-deployment-handoff.md)
  records the controlled read-only Helsinki deployment and recovery evidence.
- [`polysia-live-004-final-handoff.md`](polysia-live-004-final-handoff.md)
  records the completed bounded round trip and delayed-fill reconciliation.

All recorded Live and Tiny Live Copy authorizations are consumed. These files
do not authorize another external mutation.

## Bounded experimental evidence

- [`polysia-copy-signal-arbiter-experiment.md`](polysia-copy-signal-arbiter-experiment.md)
  records the isolated confidence-aware Arbiter and fail-closed historical
  Replay.
- [`polysia-tiny-live-copy-streaming-003.md`](polysia-tiny-live-copy-streaming-003.md)
  records response streaming, atomic signal reservation, and the scoped
  SHADOW-only workflow.
- [`polysia-tiny-live-copy-reliability-002.md`](polysia-tiny-live-copy-reliability-002.md)
  records endpoint-aware pacing, bounded recovery, and follower-management
  priority.
- [`polysia-tiny-live-copy-experiment.md`](polysia-tiny-live-copy-experiment.md)
  records the original bounded experiment design and safety controls.

## Historical retention

Completed repository-stabilization handoffs are retained in the
[historical archive](../99-archive/handoffs/repository-stabilization/). Other
historical evidence remains in this directory when it still supports current
safety, operations, or delivery claims. Consult the
[Project Status](../00-governance/PROJECT_STATUS.md) and
[Roadmap](../22-roadmap/roadmap.md) before treating any historical recommendation
as current.
