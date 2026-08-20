# Current Evidence Index

This is the canonical handoff directory selected by the Master Operating
Charter. It contains both current closure evidence and retained historical
records. Age alone does not make evidence disposable, but historical handoffs
are not automatically current operating instructions.

The Phase A baseline remains at
[`docs/13-ai-handoffs/BASELINE_AUDIT.md`](../13-ai-handoffs/BASELINE_AUDIT.md)
because that exact path is an immutable compliance artifact.

## Repository truth

- [`architecture-truth-refresh-2026-08-18.md`](architecture-truth-refresh-2026-08-18.md)
  records the repository-wide architecture audit, refreshed visual baseline,
  and automated drift prevention.
- [`polysia-upgrade-006-handoff.md`](polysia-upgrade-006-handoff.md) records the
  Python 3.14, dependency, SDK, reproducibility, and security baseline.
- [`polysia-phase-closure-005-final-handoff.md`](polysia-phase-closure-005-final-handoff.md)
  and its JSON companion record the latest completed engineering closure.

## Current safety and operational evidence

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

Other files in this directory remain retained provenance for completed
migrations, validation stages, diagnostics, and delivery work. Consult the
[Project Status](../00-governance/PROJECT_STATUS.md) and
[Roadmap](../22-roadmap/roadmap.md) before treating any historical recommendation
as current.
