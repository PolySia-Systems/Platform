# Polymarket Adapter Instructions

Scope: `src/polysia/adapters/polymarket/` and descendants. Root `AGENTS.md`
owns universal safety, Decimal, Risk authority, SDK confinement, and
Strategy -> Risk -> Execution -> Adapter. Do not repeat or weaken those rules.

## MUST

- Keep public data, authenticated account reads, execution, cancellation,
  streaming, mapping, geoblock, and reconciliation inside this adapter.
- Translate token IDs, condition IDs, market slugs, wallet/signature details,
  SDK response types, and venue-specific errors at the boundary.
- Verify version-sensitive behavior against current official documentation and
  the official SDK repository.
- Keep the pinned SDK version reproducible. Update contract tests before an
  SDK upgrade and document upgrade and rollback effects.
- Preserve signer, funder, wallet, and signature semantics unless the task
  explicitly authorizes a tested migration.

Venue-specific capability behavior may remain explicit in this adapter.
