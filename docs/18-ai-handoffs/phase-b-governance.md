# Phase B Governance Handoff

## Outcome

PolySia now has controlled project identity, scope, document authority,
registers, capability/traceability foundations, research evidence, architecture
overview, and ADR-0001 through ADR-0010. The missing Phase 0 input is represented
by an explicitly reconstructed record, not falsely presented as recovered.

Eighteen historical phase/status documents moved to
`docs/99-archive/legacy-phase-docs`. Current runbook and handoff paths required
by code remain stable. The source implementation and runtime behavior did not
change in this phase.

## Decisions

- Existing implementation remains the foundation.
- Modular monolith and inward dependency direction are accepted.
- Direct `polysia` rename is approved; no unverified compatibility shim.
- SDK b11 remains pinned during rename; b12 evaluation is separate.
- SQLite and all live safety controls are retained.
- New canonical handoffs follow the charter at `docs/18-ai-handoffs`; the
  prompt-required Phase A artifact remains at `docs/13-ai-handoffs`.

## Safety and credentials

No live network action ran. The approved `.env` was unchanged and no credential
value was written to controlled documents.

## Rollback

Revert the Phase B commit. Phase A commit `dc8ced7` and the external verified
backup remain available.

## Next action

Execute the direct package/distribution/CLI rename with mechanical inventory,
migration tests, package build/install smoke tests, and full baseline gates.

