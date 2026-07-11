# Phase E Polymarket Adapter Handoff

## Outcome

Public, secure, stream, geoblock, mapper, and capability code is consolidated
under `polysia.adapters.polymarket`. SDK imports are prohibited elsewhere by an
architecture test. Market mapping is explicit and produces canonical domain
types.

The stream boundary now wraps exhausted SDK/OS errors in `MarketStreamError`, so
the CLI no longer imports or catches an official SDK exception directly. Live
guardrails and signer/funder behavior are unchanged.

## Verification

- Compile: passed.
- Ruff: passed.
- Mypy: passed for 95 source files.
- Pytest: 342 passed.
- SDK version and required method contract tests: passed.
- SDK import confinement test: passed.
- Public read-only discovery with one market: passed on 2026-07-11.
- `pip check`: passed.
- Live/authenticated state mutation: not executed.
- Credential values: unchanged and not exposed.

## Compatibility and limitations

Public operator behavior and 34 CLI commands are preserved. SDK b11 remains
the pinned baseline. Public discovery success does not prove CLOB V2
authenticated order compatibility; that remains a controlled validation item.

## Rollback

Revert the Phase E commit to restore pre-consolidation module paths. Phase D and
the external backup remain available.

## Next action

Add CI/pre-commit/supply-chain gates and the missing integration/property test
layers, then perform controlled read-only validation before any owner-approved
state-changing test.

