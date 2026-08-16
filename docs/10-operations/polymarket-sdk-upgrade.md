# Polymarket SDK Upgrade and Rollback

## Current baseline

- Distribution: `polymarket-client`
- Import namespace: `polymarket`
- Verified version: `0.2.0`
- Status: official stable 0.x unified SDK
- Reviewed release: `0.2.0` (2026-07-24)
- Primary runtime: CPython `3.14.6`

## Upgrade procedure

1. Review only official Polymarket documentation, repository tags, changelog,
   migration notes, and relevant issues.
2. Record evidence and exact review date in the research register.
3. Create a dedicated branch and update the pyproject pin and platform locks.
4. Run SDK surface contract tests and adapter mapper/fake tests.
5. Run compile, Ruff, Mypy, all tests, dependency checks, and wheel smoke tests.
6. Run public read-only discovery/stream checks in DATA_ONLY mode.
7. With approved test credentials, run authenticated read-only diagnostics only
   in the controlled validation phase.
8. Do not run a state-changing test without explicit authorization for that run
   and every existing live safety gate.
9. Record observed signer/funder, response-shape, fee, order-type, and CLOB V2
   compatibility without recording sensitive values.

## Stop conditions

Stop if official behavior conflicts with signer/funder semantics, a contract
method is missing, canonical mapping changes silently, redaction fails, or any
live gate weakens.

## Rollback

Revert ADR-0011 and the relevant upgrade/compatibility commits before restoring
Python 3.13.14 and `polymarket-client==0.1.0b11`; those versions are not
supported by current `main`. Recreate the reverted environment, reinstall the
project, and rerun all local and public read-only gates. Never roll back by
changing or replacing credential values.
