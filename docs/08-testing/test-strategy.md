# Test Strategy

PolySia uses risk-based layers:

- `tests/unit`: deterministic component behavior;
- `tests/property`: invariants across generated financial inputs;
- `tests/architecture`: dependency direction and SDK confinement;
- `tests/contract`: pinned external SDK surface;
- `tests/integration`: multi-component vertical slices and persistence;
- `tests/migration`: distribution, namespace, CLI, and legacy removal;
- future `tests/e2e`: packaged operator workflows with no live mutation.

Ordinary tests and CI force DATA_ONLY mode, disable the live flag, and clear the
live token allowlist. They must not receive test or production credentials.
Network tests are opt-in and read-only unless a separately marked controlled
validation has explicit owner authorization for that specific run.

Every meaningful phase runs compile, Ruff, Mypy, pytest, and `pip check`.
Packaging phases also run build and installed-wheel smoke tests. Supply-chain
gates include a tracked-file secret scan, dependency audit, and CycloneDX SBOM.

Priority test subjects are order states, Decimal arithmetic, risk limits,
idempotency, duplicates/out-of-order events, restart/recovery, reconciliation,
redaction, SDK contracts, and negative proofs for live gates.
