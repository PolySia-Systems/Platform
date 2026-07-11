# Phase D Domain and Ports Handoff

## Outcome

PolySia now has venue-neutral domain packages for markets/venues, events,
orders/intents/fills, portfolio, risk, ledger, reconciliation, and deterministic
clocks. Application protocols cover market catalog/data, execution, account
reads, repositories, event bus, emergency control, and clock access.

`MarketSummary`, `MarketDetails`, and outcomes moved out of the Polymarket
adapter. Strategies and SQLite repositories now import canonical domain models.
Existing execution intent imports remain compatible through a domain re-export,
and market-data events now originate in the domain with a generic source ID.

Architecture tests prevent domain/application imports from the Polymarket SDK or
adapter layer and prevent strategy/storage imports from venue adapters.

## Verification

- Compile: passed.
- Ruff: passed.
- Mypy: passed for 93 source files.
- Pytest: 337 passed.
- Architecture boundary tests: passed.
- No live or authenticated network action ran.
- Credential configuration was unchanged and values were not exposed.

## Compatibility

Public behavior is unchanged. Existing imports through
`polysia.execution.intents` and `polysia.bus.events` remain valid while the
underlying canonical types live in `polysia.domain`.

## Remaining coupling

Execution and monitoring modules still import concrete Polymarket adapter types
for live workflows. Phase E will consolidate those modules under
`polysia.adapters.polymarket` and strengthen adapter contracts without altering
safety gates.

## Rollback

Revert the Phase D commit. Phase C commit `d8fb60d` remains the identity baseline.

