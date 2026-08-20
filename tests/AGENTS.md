# Test Suite Instructions

- Keep test categories responsibility-based and preserve their layer boundaries.
- Ordinary tests must not mutate external accounts or services; network tests must be explicit and opt-in.
- Keep fixtures near their owning tests unless they are intentionally shared across test layers.
- Do not mix behavior changes with taxonomy-only moves.
- Do not weaken safety, contract, architecture, property, reconciliation, or credential-redaction coverage.
