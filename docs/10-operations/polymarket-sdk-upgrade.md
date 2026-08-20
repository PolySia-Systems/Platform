# Polymarket SDK Upgrade and Rollback

## Current baseline

- Distribution: `polymarket-client`
- Import namespace: `polymarket`
- Verified version: `0.6.0`
- Status: official stable 0.x unified SDK
- Reviewed release: `0.6.0` (2026-08-13)
- Primary runtime: CPython `3.14.6`

The 2026-08-21 review covered each official stable release from 0.2.0 through
0.6.0. Relevant changes include broader activity defaults in 0.3.0, isolated
margin and tick-size documentation in 0.4.0, order-market metadata caching in
0.5.0, and combo RFQ plus sparse-last-trade handling in 0.6.0. PolySia does not
consume the new perps or combo RFQ surfaces. The distribution dependency set is
unchanged from 0.2.0, so the migration does not require transitive lock churn.

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

Revert the 0.6.0 migration commits as one unit. This restores the direct pin,
both portable locks, approved runtime constants, SDK contracts, and current
documentation to 0.2.0 without changing Python support. Recreate the reverted
environment, reinstall the project, and rerun all local and public read-only
gates before promotion. Restoring Python 3.13.14 and SDK 0.1.0b11 is a separate
historical compatibility rollback. Never roll back by changing or replacing
credential values.
