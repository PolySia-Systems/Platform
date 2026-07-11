# Project Progress Report

This report summarizes the Polymarket trading system work from the initial
scaffold through the verified live connectivity smoke test.

## Current Status

The project is a professional, data-first Polymarket trading system. It is
stable through Phase 25 tiny live execution on branch
`chore/live-smoke-test-e2e`.

Default mode remains safe:

- `TRADING_MODE=DATA_ONLY`
- `LIVE_TRADING_ENABLED=false`
- dry-run defaults on live commands
- no strategy-connected live trading by default
- mandatory geoblock before live order placement

## Phase Summary

- Phase 0: Created the base project scaffold, configuration model, logging,
  CLI health command, and test setup.
- Phase 1: Added public Polymarket market discovery using the public SDK path.
- Phase 2: Added realtime market stream ingestion, normalized market events,
  and an in-memory event bus.
- Phase 3: Built the local Decimal-based orderbook engine and orderbook
  builder.
- Phase 4: Added SQLite storage repositories and schema for events, markets,
  orderbook snapshots, and local audit/state records.
- Phase 5: Added the strategy framework, order intents, microstructure
  features, and a simple stale-price research strategy.
- Phase 6: Added pre-trade risk checks, position/order limits, and a kill
  switch.
- Phase 7: Added conservative paper execution, paper fills, position tracking,
  and PnL accounting.
- Phase 8: Added the authenticated secure adapter and live broker guardrails,
  with live trading still disabled by default.
- Phase 9: Added limited live account reads and dry-run-first cancel operations
  behind LIVE mode and acknowledgement flags.
- Phase 10: Added a controlled tiny live limit-order path with hard caps,
  allowlist checks, dry-run default, and explicit acknowledgement.
- Phase 11: Added sanitized operator metrics and operator status snapshots.
- Phase 12: Added static operator reports in JSON, Markdown, and HTML, with
  secret redaction.
- Phase 13: Added deterministic JSONL replay backtesting with paper execution.
- Phase 14: Added a research-only passive market-making strategy for paper and
  backtest use only.
- Phase 15: Added deployment-readiness checks, including live guardrails,
  secret-safe defaults, and geoblock readiness.
- Phase 16: Added generated and checked-in operator runbooks.
- Phase 17: Added sanitized release handoff manifests and package metadata
  checks.
- Phase 18: Added local deployment automation for tests, lint, type checks,
  readiness, release manifest, and runbook artifacts.
- Phase 19: Completed final project handoff with generated sanitized release
  artifacts.
- Phase 20.5: Added the guarded live connectivity smoke test, BTC 5m
  auto-selection, signer/funder diagnostics, and one verified real 1 USDC smoke
  order path.
- Phase 20: Added acceptance audit and shadow-production simulation with
  safety checks, system checks, paper-only strategy/risk/fill/PnL metrics, and
  sanitized JSON/Markdown/HTML reports.
- Phase 21: Added real-time shadow-run reporting with paper-only time-series
  metrics, shadow health classification, and sanitized JSON/Markdown/HTML/JSONL
  outputs.
- Phase 22: Added read-only strategy evaluation and calibration reports for
  backtest, shadow-run, audit, paper, and JSONL results, including signal,
  execution, PnL, risk, Brier score, calibration buckets, small sample warnings,
  and human-review classification.
- Phase 23: Added read-only fill simulation accuracy reports with conservative,
  top-of-book, and deterministic queue-aware fill models, partial/missed fill
  accounting, slippage, paper PnL by model, conservatism scoring, and
  optimistic-model warnings.
- Phase 24: Added a final no-live-order tiny live readiness gate that aggregates
  deployment readiness, final handoff, acceptance audit, shadow run, strategy
  evaluation, fill simulation, geoblock enforcement, kill switch, allowlist,
  tiny caps, signer/funder diagnostics, strategy/live isolation, and secret
  redaction.
- Phase 25: Added a guarded one-attempt tiny live execution command for BTC
  Up/Down 5m operator-selected tokens already in the live token allowlist, with
  dry-run default, hard 1 USDC cap, FAK/FOK only, mandatory geoblock, kill
  switch, risk approval, signer/funder diagnostics, no retry, and sanitized
  JSON/Markdown/HTML reports.

## Key Safety Decisions

- Secrets are never committed and `.env` remains ignored.
- Reports, logs, readiness checks, and runbooks expose only safe booleans,
  counts, caps, and statuses.
- Live order placement requires LIVE mode, `LIVE_TRADING_ENABLED=true`,
  explicit acknowledgement, token allowlist, tiny caps, inactive kill switch,
  risk approval, and geoblock eligibility.
- The official Polymarket geoblock endpoint is mandatory before live order
  placement.
- Geoblock errors fail closed.
- The live smoke test is not a strategy, profitability test, market maker, or
  repeated trading loop.

## Live Connectivity Work

The live smoke test initially connected to the secure SDK but aborted before
order placement. The old working project showed the correct wallet pattern:

```text
signer = login EOA private key
funder = Polymarket trading proxy wallet
```

The new project was updated so the secure adapter passes
`POLYMARKET_FUNDER_ADDRESS` as the SDK wallet/funder value while keeping
`POLYMARKET_PRIVATE_KEY` as the signer key. Diagnostics now confirm signer and
funder configuration without printing addresses.

The live account diagnostic confirmed:

- signer configured
- funder configured
- active wallet source is funder
- balance readable
- approval readable
- positive approvals present
- open orders readable
- positions readable

Dry-run BTC 5m auto-selection passed. Then a real FOK BUY smoke test returned
`final_result=PASS` and the account UI showed an about 1 USDC Up purchase. A
second immediate FOK run was rejected after the market moved, which is normal
for FOK and does not invalidate the successful connectivity test.

## Current Verification

After Phase 25:

- `python -m pytest`: 239 passed
- `python -m ruff check .`: passed
- `python -m mypy src`: passed
- secret scan for known provided values: no matches in tracked project files
- live smoke dry-run: PASS
- real one-order smoke path: PASS on first real run
- acceptance-audit: added as a no-live-order audit command
- shadow-run: added as a no-live-order paper-only reporting command
- strategy-evaluation: added as a no-live-order strategy quality and
  calibration reporting command
- fill-simulation-audit: added as a no-live-order paper fill realism and
  conservatism reporting command
- tiny-live-readiness: added as a no-live-order final tiny-live review gate
- tiny-live-execute: added as a dry-run-first, one-attempt maximum tiny live
  execution command

## Current Git State

Important commits on `chore/live-smoke-test-e2e`:

- `208819b Phase 20.5 live connectivity smoke test`
- `47c36ce Add BTC 5m auto-selection for live smoke test`
- `3960038 Fix signer funder handling for live smoke test`

This branch has not been merged into `main`.

## Recommended Next Step

Keep the branch for review and audit. Do not keep repeating real smoke orders.
The connectivity question is answered. The next decision is whether to keep
Phase 20.5 as a permanent guarded operator tool and later merge it into `main`
after review.
