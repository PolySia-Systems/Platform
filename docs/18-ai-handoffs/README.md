# Evidence Index

Ordinary in-progress work resumes from the GitHub Issue or PR. This directory
holds major operational, safety, deployment, incident, and compliance
evidence that must outlive a single PR. Chat history is not a source of
truth.

The immutable baseline remains at
[`docs/13-ai-handoffs/BASELINE_AUDIT.md`](../13-ai-handoffs/BASELINE_AUDIT.md)
because that exact path is an immutable compliance artifact.

## Current operational evidence

- [`stage4b-data-lifecycle-v1.md`](stage4b-data-lifecycle-v1.md)
  is the current Stage 4B storage-lifecycle evidence: schema v6, compact
  cutover, T0, and 24-hour storage acceptance.
- [`stage4b-data-ownership-cutover.md`](stage4b-data-ownership-cutover.md)
  remains the preceding standalone schema-v5 ownership and recovery record.
- [`polysia-finland-wallet-intelligence-deployment.md`](polysia-finland-wallet-intelligence-deployment.md)
  records the Helsinki DATA_ONLY Stages 1–4 deployment, backup/restore,
  rollback, and `3x-ui` preservation evidence.

These files do not authorize Live trading or another external mutation.

## Superseded Stage 4B evidence

Still retained for provenance. Do not treat them as current operating
instructions.

- [`cs-lease-recovery-telemetry-isolation.md`](cs-lease-recovery-telemetry-isolation.md)
- [`wallet-intelligence-stage4b-v4-reliability.md`](wallet-intelligence-stage4b-v4-reliability.md)
- [`wallet-intelligence-stage4b-continuous-shadow.md`](wallet-intelligence-stage4b-continuous-shadow.md)
  (last verified Helsinki schema-v3 runtime evidence)

## Historical safety and Live evidence

All recorded Live and Tiny Live Copy authorizations are consumed.

- [`polysia-tiny-live-copy-004-cancellation-diagnostic.md`](polysia-tiny-live-copy-004-cancellation-diagnostic.md)
- [`polysia-post-only-final-recheck.md`](polysia-post-only-final-recheck.md)
- [`polysia-controlled-server-deployment-handoff.md`](polysia-controlled-server-deployment-handoff.md)
- [`polysia-live-004-final-handoff.md`](polysia-live-004-final-handoff.md)
- [`polysia-tiny-live-copy-streaming-003.md`](polysia-tiny-live-copy-streaming-003.md)
- [`polysia-tiny-live-copy-reliability-002.md`](polysia-tiny-live-copy-reliability-002.md)
- [`polysia-tiny-live-copy-experiment.md`](polysia-tiny-live-copy-experiment.md)

## Historical delivery evidence

- [`latency-performance-intelligence-v0-1.md`](latency-performance-intelligence-v0-1.md)
- [`wallet-intelligence-stage4-dynamic-shadow.md`](wallet-intelligence-stage4-dynamic-shadow.md)
- [`wallet-intelligence-stage3.md`](wallet-intelligence-stage3.md)
- [`wallet-intelligence-stage2.md`](wallet-intelligence-stage2.md)
- [`polycop-candidate-wallet-ingestion.md`](polycop-candidate-wallet-ingestion.md)
- [`architecture-truth-refresh-2026-08-18.md`](architecture-truth-refresh-2026-08-18.md)
- [`polysia-upgrade-006-handoff.md`](polysia-upgrade-006-handoff.md)
- [`polysia-phase-closure-005-final-handoff.md`](polysia-phase-closure-005-final-handoff.md)
- [`polysia-copy-signal-arbiter-experiment.md`](polysia-copy-signal-arbiter-experiment.md)
- [`polysia-tiny-live-copy-diagnostic-handoff.md`](polysia-tiny-live-copy-diagnostic-handoff.md)
- [`polysia-copytrading-stage1-data-feasibility.md`](polysia-copytrading-stage1-data-feasibility.md)
- [`polysia-copytrading-architecture-spike.md`](polysia-copytrading-architecture-spike.md)
- [`polysia-live-003-final-handoff.md`](polysia-live-003-final-handoff.md)
- [`polysia-live-002-final-handoff.md`](polysia-live-002-final-handoff.md)
- [`polysia-live-001-final-handoff.md`](polysia-live-001-final-handoff.md)

Completed repository-stabilization handoffs remain in the
[historical archive](../99-archive/handoffs/repository-stabilization/). Other
files in this directory remain provenance when they still support safety,
operations, or delivery claims. Consult
[Project Status](../00-governance/PROJECT_STATUS.md) and
[Roadmap](../22-roadmap/roadmap.md) before treating any historical
recommendation as current work.
