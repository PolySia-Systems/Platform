# Polymarket SDK Upgrade and Rollback

## Current baseline

- Distribution: `polymarket-client`
- Import namespace: `polymarket`
- Verified version: `0.7.1`
- Status: official stable 0.x unified SDK
- Reviewed release: `0.7.1` (2026-08-28)
- Primary runtime: CPython `3.14.7`

The 2026-09-03 review covered official stable releases 0.7.0 and 0.7.1 after
the previously verified 0.6.0 pin. 0.7.0 adds scoped session keys, typed
trading-restriction errors, trading-approvals state, typed notification
payloads, and Poly-RateLimit surfaces. 0.7.1 is a session-key expiration patch.
PolySia does not consume the new perps, combo RFQ, session-key, or rate-limit
callback surfaces. Consumed public/secure methods, signer/funder creation
inputs, bounded-order parameters, and adapter confinement remain compatible.
Tiny Live approved-runtime constants now require exactly `0.7.1`.

## Verified order and cancellation contract

The 2026-08-21 contract review verified the official `OpenOrder` wire aliases
(`market`, `asset_id`, `expiration`, and timestamp fields), Decimal parsing,
durable order/trade identifiers, and `CancelOrdersResponse` with both
`canceled` and `not_canceled` results. Deterministic local fixtures pin these
consumed shapes. The 2026-09-03 upgrade revalidated the same contract tests
against 0.7.1 without changing those fixture semantics.

The secure adapter returns an explicit not-found result only for a verified
HTTP 404. Invalid, malformed, unavailable, or unexpected order-detail payloads
remain sanitized errors and cannot prove terminal absence. Open-order reads
consume every SDK page before account-wide cancellation evidence is considered
complete.

## Upgrade procedure

1. Review only official Polymarket documentation, repository tags, changelog,
   migration notes, and relevant issues.
2. Record evidence and exact review date in the research register.
3. Create a dedicated branch and update the pyproject pin and platform locks.
4. Update approved Tiny Live SDK constants together with the pin.
5. Run SDK surface contract tests and adapter mapper/fake tests.
6. Run compile, Ruff, Mypy, all tests, dependency checks, and wheel smoke tests.
7. Run public read-only discovery/stream checks in DATA_ONLY mode.
8. With approved test credentials, run authenticated read-only diagnostics only
   in the controlled validation phase.
9. Do not run a state-changing test without explicit authorization for that run
   and every existing live safety gate.
10. Record observed signer/funder, response-shape, fee, order-type, and CLOB V2
    compatibility without recording sensitive values.

## Stop conditions

Stop if official behavior conflicts with signer/funder semantics, a contract
method is missing, canonical mapping changes silently, redaction fails, or any
live gate weakens.

## Rollback

To roll back only cancellation contract hardening, revert its focused commits;
no dependency, lock, schema, or credential migration is involved. This removes
the finality gate and canonical evidence mappings but restores the known unsafe
single-read limitation, so do not promote or run the Tiny Live path afterward.

Revert the 0.7.1 pin, portable locks, approved runtime constants, SDK
contracts, and current documentation as one unit to restore 0.6.0. Recreate the
reverted environment, reinstall the project, and rerun all local and public
read-only gates before promotion. Never roll back by changing or replacing
credential values.
