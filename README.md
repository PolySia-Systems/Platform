# PolySia — Polymarket Adapter

Professional, data-first prediction-market platform with a Polymarket adapter.

Current scope includes project structure, safe configuration, public market
discovery, realtime market stream ingestion, an in-memory event bus, a local
Decimal orderbook engine, SQLite-backed storage repositories, a strategy
framework, pre-trade risk controls, a conservative paper broker, portfolio/PnL
tracking, a secure live adapter guarded by dry-run defaults, and tests. Live
trading remains disabled by default, the default mode is always `DATA_ONLY`, and
deployment-readiness checks, operator runbooks, and release manifests are
sanitized. Local deployment automation and final handoff commands write ignored
release artifacts.

## Safety Rules

- Do not commit private keys, API keys, wallet secrets, or generated `.env` files.
- Default runtime mode is `TRADING_MODE=DATA_ONLY`.
- `POLYMARKET_PRIVATE_KEY` is the signer/login EOA private key.
- `POLYMARKET_FUNDER_ADDRESS` is the Polymarket trading proxy/funder wallet.
- Do not use the login EOA wallet address as `POLYMARKET_FUNDER_ADDRESS`.
- `POLYMARKET_SIGNATURE_TYPE=3` can be set for diagnostics; the new SDK derives
  the actual order signature type from the detected wallet type.
- `POLYMARKET_LIVE_TOKEN_ALLOWLIST` must contain any token IDs allowed for actual live submit/cancel.
- Tiny live orders are capped by `POLYMARKET_LIVE_MAX_ORDER_SIZE`,
  `POLYMARKET_LIVE_MAX_ORDER_NOTIONAL`, and `POLYMARKET_LIVE_MAX_OPEN_ORDERS`.
- `LIVE_TRADING_ENABLED=false` is the default.
- Live order submission refuses to run unless `TRADING_MODE=LIVE`,
  `LIVE_TRADING_ENABLED=true`, the kill switch is inactive, risk approves, and
  the explicit confirmation flag is supplied by the caller.
- Actual live submit/cancel refuses to run unless the target token is allowlisted.
- Actual live smoke submit refuses to run unless `POLYMARKET_FUNDER_ADDRESS` is set.
- Dry-run mode logs a sanitized intended order request and does not submit or cancel.
- Trading quantities in later phases must use `Decimal`, not float arithmetic.

## Setup

Use the existing conda environment:

```powershell
conda activate PolySia
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` only when local overrides are needed. Keep real
secrets out of git.

## First Run

```powershell
python -m polysia.cli health
```

Expected result: a JSON health response with `status` set to `ok`.

## Public Market Discovery

```powershell
python -m polysia.cli discover-markets --limit 10
```

This command uses the official public Polymarket SDK and does not require keys.

## Realtime Market Stream

```powershell
python -m polysia.cli stream-market --token-id YOUR_TOKEN_ID --max-events 1
```

The stream command subscribes to public market events, normalizes SDK messages,
and prints JSON lines. It does not trade.

## Paper Trading Demo

```powershell
python -m polysia.cli paper-trade --token-id YOUR_TOKEN_ID --order-size 1
```

This command runs a deterministic local simulation from a synthetic orderbook:
strategy intent, risk approval, conservative paper fill, position update, and
PnL calculation. It does not call live trading APIs.

## Secure Live Adapter

Phase 8 adds the authenticated adapter and live broker guardrails, but does not
enable live trading. The live broker defaults to dry-run behavior and every
submission path is protected by settings, kill switch, risk approval, and an
explicit acknowledgement flag.

## Limited Live Account Operations

Phase 9 opens only the first safe live slice: authenticated open-order reads and
dry-run-first cancellations. Reads require `TRADING_MODE=LIVE` and an explicit
live-account acknowledgement. Actual cancellations also require
`LIVE_TRADING_ENABLED=true` and an allowlisted token.

```powershell
python -m polysia.cli live-open-orders --token-id YOUR_TOKEN_ID --i-understand-this-uses-live-account
python -m polysia.cli live-cancel-market-orders --token-id YOUR_TOKEN_ID --dry-run --i-understand-this-modifies-live-orders
```

## Tiny Live Limit Orders

Phase 10 adds a dry-run-first operator command for one tiny post-only limit
order. Actual submission requires LIVE mode, `LIVE_TRADING_ENABLED=true`, token
allowlist membership, the tiny live caps, `--submit`, and
`--i-understand-this-places-real-orders`.

```powershell
python -m polysia.cli live-limit-order --token-id YOUR_TOKEN_ID --side BUY --price 0.01 --size 1 --dry-run --i-understand-this-places-real-orders
```

## Live Connectivity Smoke Test

Phase 20.5 adds one guarded end-to-end connectivity smoke test for a separate
test wallet. It is not a strategy, market-making, or retrying order loop. It
defaults to dry-run and requires LIVE mode, `LIVE_TRADING_ENABLED=true`, an
allowlisted token, explicit `POLYMARKET_FUNDER_ADDRESS`, FAK/FOK order type,
the official Polymarket geoblock check returning `blocked=false`, and the
explicit real-order acknowledgement before one live order attempt can be
submitted.

For BUY smoke tests, `--max-notional` is the dollar amount sent to the market
order path and remains capped at 1 USDC. CLOB `min_order_size` is recorded in
the report, but the smoke test does not automatically increase size to satisfy
it. If the SDK or exchange rejects the tiny order, the report records the
rejection instead of retrying.

```powershell
python -m polysia.cli live-smoke-test --market-slug BTC_5M_MARKET_SLUG --condition-id CONDITION_ID --token-id TOKEN_ID --outcome YES --side BUY --max-notional 1.00 --order-type FAK --dry-run
python -m polysia.cli live-smoke-test --auto-btc-5m --outcome YES --side BUY --max-notional 1.00 --order-type FAK --dry-run
python -m polysia.cli live-account-status --redact-secrets
```

Troubleshooting and the verified signer/funder pattern are documented in
`docs/LIVE_CONNECTIVITY_SMOKE_TEST.md`.

## Acceptance Audit

Phase 20 adds a no-live-order acceptance audit and shadow-production simulation.
It verifies safety gates, deployment readiness, release/runbook/handoff
availability, normalized market events, local orderbook updates, strategy
paper intents, risk evaluation, paper fills, position/PnL updates, and confirms
that no live broker is used.

```powershell
python -m polysia.cli acceptance-audit
python -m polysia.cli acceptance-audit --require-clean-git --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_20_ACCEPTANCE_AUDIT.md`.

## Shadow Run Reports

Phase 21 adds repeatable paper-only shadow-run reporting. It produces
time-series metrics for mocked public market events, local orderbook updates,
strategy intents, risk decisions, paper fills, position/PnL, drawdown, and
decision latency. It does not use the live broker.

```powershell
python -m polysia.cli shadow-run
python -m polysia.cli shadow-run --max-events 6 --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_21_SHADOW_RUN.md`.

## Strategy Evaluation

Phase 22 adds read-only strategy evaluation and calibration reports from
backtest, shadow-run, audit, paper, or JSONL result files. It calculates signal,
execution, PnL, risk, and calibration quality, including Brier score and
probability buckets. It does not use the live broker and never approves actual
live trading.

```powershell
python -m polysia.cli strategy-evaluation --input .\release-artifacts\shadow_run.json --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_22_STRATEGY_EVALUATION.md`.

## Fill Simulation Audit

Phase 23 adds read-only fill simulation accuracy reports. It compares
conservative, top-of-book, and deterministic queue-aware paper fill models
against orderbook conditions, including partial fills, missed fills, slippage,
paper PnL, and optimistic-model warnings. It does not use the live broker.

```powershell
python -m polysia.cli fill-simulation-audit --input .\backtest_result.json --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_23_FILL_SIMULATION.md`.

## Tiny Live Readiness

Phase 24 adds a final conservative readiness gate for future tiny-live review.
It aggregates deployment readiness, final handoff, acceptance audit, shadow
run, strategy evaluation, fill simulation, geoblock enforcement, signer/funder
diagnostics, kill switch availability, allowlist status, tiny caps, and secret
redaction. It does not place or approve live orders.

```powershell
python -m polysia.cli tiny-live-readiness --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_24_TINY_LIVE_READINESS.md`.

## Tiny Live Execution

Phase 25 adds one guarded tiny live execution command. It defaults to dry-run
and is restricted to BTC Up/Down 5m operator-selected tokens already present in
`POLYMARKET_LIVE_TOKEN_ALLOWLIST`. A real submit requires LIVE mode, live flag,
explicit acknowledgement, geoblock allowed, inactive kill switch, signer/funder
configured, balance/approval readable, risk approval, and exactly one submit
attempt maximum.

```powershell
python -m polysia.cli tiny-live-execute --token-id TOKEN_ID_FROM_ALLOWLIST --side BUY --outcome YES --max-notional 1.00 --order-type FAK --market-slug btc-updown-5m-example --dry-run --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_25_TINY_LIVE_EXECUTION.md`.

## Post-Live Reconciliation

Phase 26 adds a read-only reconciliation report after a successful tiny live
fill. It checks git state, live flags, kill switch status, deployment readiness,
final handoff availability, the sanitized tiny live result, account readability,
open order count, signer/funder booleans, allowlist count, and geoblock status.
It never submits or cancels orders.

```powershell
python -m polysia.cli post-live-reconciliation --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_26_POST_LIVE_RECONCILIATION.md`.

## Observability Snapshot

Phase 27 adds a dashboard-friendly observability snapshot for operators. It
summarizes runtime mode, live flag state, kill switch status, live path
readiness, public data status, stream health, orderbook freshness, paper
trading status, strategy/backtest status, open-order read status, last tiny live
result, latency metrics, warning counts, and blocking counts. It is read-only
and never submits or cancels live orders.

```powershell
python -m polysia.cli observability-snapshot --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_27_OBSERVABILITY.md`.

## Real Data Shadow Run

Phase 28 adds a paper-only shadow run that uses public market discovery and
public realtime stream events. It normalizes events, updates the local
orderbook, runs a research strategy, passes intents through risk checks, and
uses the paper broker only. It never calls the live broker, never submits live
orders, and never cancels live orders.

```powershell
python -m polysia.cli shadow-run-real-data --auto-btc-5m --max-events 100 --output-dir .\release-artifacts
python -m polysia.cli shadow-run-real-data --market-slug MARKET_SLUG --strategy passive-market-maker --max-events 100 --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_28_REAL_DATA_SHADOW_RUN.md`.

## Extended Strategy Evaluation

Phase 29 adds a read-only extended strategy evaluation over replay, paper,
backtest, or real-data shadow artifacts. It reports signal, risk, execution,
PnL, drawdown, and calibration metrics without using the live broker or writing
secret identifiers to artifacts.

```powershell
python -m polysia.cli strategy-evaluation-extended --input .\release-artifacts\shadow-run-real-data.json --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_29_EXTENDED_STRATEGY_EVALUATION.md`.

## Tiny Live Monitor

Phase 30 adds a read-only tiny live monitor for the test account and project
state. It checks geoblock status, signer/funder configuration, balance and
approval readability, open-order count, and the latest safety artifacts without
submitting or canceling any live order.

```powershell
python -m polysia.cli tiny-live-monitor --output-dir .\release-artifacts --redact-secrets
```

Details are documented in `docs/PHASE_30_TINY_LIVE_MONITOR.md`.

## Controlled Second Tiny Live

Phase 31 adds a stricter dry-run-first path for a possible second tiny live
connectivity test. It defaults to dry-run and a real submit remains impossible
unless `--submit`, both acknowledgement flags, LIVE mode, geoblock, allowlist,
signer/funder, account readability, risk approval, and the one-attempt guard all
pass.

```powershell
python -m polysia.cli controlled-second-tiny-live --auto-btc-5m --side BUY --outcome YES --max-notional 1.00 --order-type FOK --dry-run --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_31_CONTROLLED_SECOND_TINY_LIVE.md`.

## Production Gap Audit

Phase 32 adds a read-only release freeze and production gap audit. It classifies
capabilities as production-ready, MVP-ready, research-only, paper-only,
blocked-for-live, or requires-human-review, and documents the merge plan and
operator decision before any main merge.

```powershell
python -m polysia.cli production-gap-audit --output-dir .\release-artifacts
```

Details are documented in
`docs/PHASE_32_RELEASE_FREEZE_AND_PRODUCTION_GAP_AUDIT.md`.

## Main Merge Review

Phase 33 adds a local release-owner review package for tag verification and a
controlled merge to `main`. Missing GitHub remote is reported as a warning only
and does not block local review.

```powershell
python -m polysia.cli main-merge-review --output-dir .\release-artifacts
```

Details are documented in
`docs/PHASE_33_HUMAN_RELEASE_REVIEW_AND_MAIN_MERGE.md`.

## Final Local Release Closeout

Phase 34 finalizes the local release package after Phase 33. It is
release-management only: it does not approve live trading, second real tiny
live tests, capital scaling, live market making, or live strategy automation.
Missing GitHub remote remains a warning only for local finalization.

```powershell
python -m polysia.cli local-release-closeout --output-dir .\release-artifacts
```

Details are documented in `docs/FINAL_LOCAL_RELEASE_CLOSEOUT.md`.

## Reconciliation Manager

Phase 35 adds a read-only reconciliation manager for manual-intervention
detection. It compares internal expected state with external account state when
explicit read-only live-account acknowledgement is provided. Mismatches pause
trading and require manual acknowledgement; the command never places, cancels,
modifies, retries, or automates live orders.

```powershell
python -m polysia.cli reconcile-account --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_35_RECONCILIATION_MANAGER.md`.

## Controlled Manual Intervention Live Test

Phase 36 adds a guarded manual-intervention test harness. It defaults to dry-run.
The real path can submit at most one tiny BTC Up/Down 5m BUY order, then switches
to read-only reconciliation polling so the operator can manually cancel the open
order or close the resulting position from the Polymarket website. Detection
pauses trading and reports `MANUAL_INTERVENTION_DETECTED`.

```powershell
python -m polysia.cli manual-intervention-live-test --auto-btc-5m --outcome YES --side BUY --max-notional 1.00 --order-type FOK --dry-run --output-dir .\release-artifacts
```

Details are documented in `docs/PHASE_36_CONTROLLED_MANUAL_INTERVENTION_LIVE_TEST.md`.

## Operator Metrics

Phase 11 adds sanitized operator metrics for readiness checks and dashboards.
The command reports trading mode, live caps, allowlist count, kill-switch state,
and whether tiny live orders are ready. It reports only whether keys/wallets are
configured, never their values.

```powershell
python -m polysia.cli operator-status
```

## Operator Reports

Phase 12 adds static sanitized operator reports in JSON, Markdown, or HTML. The
HTML output is a local file-friendly dashboard and still includes only safe
status fields, counts, caps, and warnings.

```powershell
python -m polysia.cli operator-report --format html --output .\operator-report.html
python -m polysia.cli operator-report --format markdown
```

## Replay Backtesting

Phase 13 adds deterministic JSONL replay backtests. The replay path rebuilds
local books, runs the selected strategy, applies the risk engine, and uses only
the conservative paper broker. It never calls live trading APIs.

```powershell
python -m polysia.cli backtest-jsonl --input .\events.jsonl --strategy stale-price --initial-cash 100
python -m polysia.cli backtest-jsonl --input .\events.jsonl --strategy passive-market-maker --min-edge 0.05
```

## Market-Making Research

Phase 14 adds a research-only passive market-making strategy. It joins the best
bid/ask without crossing the spread, respects a max inventory cap, and is wired
only into paper trading and replay backtests. It does not add any live market
making path.

## Deployment Readiness

Phase 15 adds a sanitized readiness check for release handoffs. It verifies
required project files, safe `.env.example` defaults, secret-protecting
`.gitignore` patterns, live-trading guardrails, tiny live caps, mandatory
geoblock enforcement status, and optionally a clean git worktree. It never
prints secrets, wallet addresses, or allowlisted token values.

```powershell
python -m polysia.cli deployment-readiness
python -m polysia.cli deployment-readiness --require-clean-git
```

## Operator Runbook

Phase 16 adds a generated operator runbook and a checked-in manual runbook at
`docs/OPERATOR_RUNBOOK.md`. The generated runbook combines sanitized operator
status and deployment-readiness output with safe operating steps for start of
day, public data collection, research loops, reporting, live dry-runs, and
emergency stop.

```powershell
python -m polysia.cli operator-runbook
python -m polysia.cli operator-runbook --include-live --output .\operator-runbook.md
```

## Release Manifest

Phase 17 adds a sanitized release handoff manifest and a checked-in handoff
guide at `docs/RELEASE_HANDOFF.md`. The manifest captures package metadata,
CLI entrypoint configuration, git commit/clean status, deployment readiness, and
release-blocking checks without printing secrets or account values.

```powershell
python -m polysia.cli release-manifest
python -m polysia.cli release-manifest --require-clean-git --output .\release-manifest.json
```

## Deployment Automation

Phase 18 adds one local deployment automation command. It runs unit tests, lint,
type checks, deployment readiness, release manifest generation, and operator
runbook generation, then writes sanitized ignored artifacts under
`release-artifacts/`.

```powershell
python -m polysia.cli deployment-automation
python -m polysia.cli deployment-automation --require-clean-git --include-live-runbook
```

## Final Handoff

Phase 19 adds the final project handoff command and a checked-in guide at
`docs/FINAL_HANDOFF.md`. It runs deployment automation, writes the release
manifest, operator runbook, automation result, and final handoff summary under
`release-artifacts/`.

```powershell
python -m polysia.cli final-handoff
python -m polysia.cli final-handoff --require-clean-git
```

## Checks

```powershell
python -m pytest
python -m ruff check .
python -m mypy src
```

## Local Storage

Phase 4 uses SQLite as the MVP persistence layer for events, market metadata,
orderbook snapshots, and audit/state records. Local database files such as
`*.sqlite3` are ignored by git.

## Phase Boundaries

- Phase 0: scaffold, config, logging, CLI health, tests.
- Phase 1: public Polymarket SDK adapter and real market discovery.
- Phase 2: realtime stream ingestion, normalized market-data events, in-memory bus.
- Phase 3: local Decimal orderbook engine and builder.
- Phase 4: SQLite storage repositories and schema.
- Phase 5: strategy interface, order intents, microstructure features, toy stale-price strategy.
- Phase 6: pre-trade risk engine, limits, and kill switch.
- Phase 7: conservative paper broker, order/fill state, positions, and PnL.
- Phase 8: authenticated secure adapter, live broker hard gates, and sanitized dry-run.
- Phase 9: live account read/cancel operations with dry-run defaults and token allowlist.
- Phase 10: controlled tiny post-only live limit orders with risk caps and dry-run defaults.
- Phase 11: sanitized operator status and metrics snapshots.
- Phase 12: static sanitized operator reports in JSON, Markdown, and HTML.
- Phase 13: deterministic JSONL replay/backtesting with paper execution.
- Phase 14: research-only passive market-making strategy for paper/backtests.
- Phase 15: sanitized deployment-readiness checks for release handoffs.
- Phase 16: generated and checked-in operator runbooks.
- Phase 17: sanitized release handoff manifest and package metadata checks.
- Phase 18: local deployment automation and ignored release artifacts.
- Phase 19: final review and generated project handoff summary.
- Phase 20.5: guarded live connectivity smoke test, BTC 5m auto-selection, and
  signer/funder diagnostics.
- Phase 20: acceptance audit and shadow-production simulation without live
  orders.
- Phase 21: paper-only shadow-run reports with time-series metrics.
- Phase 22: strategy evaluation and calibration reports.
- Phase 23: fill simulation accuracy audit.
- Phase 24: tiny live readiness gate.
- Phase 25: guarded one-attempt tiny live execution.
- Phase 26: post-live reconciliation and release freeze checks.
- Phase 27: sanitized observability snapshot and dashboard artifacts.
- Phase 28: public real-data, paper-only shadow run.
- Phase 29: extended strategy evaluation over replay and shadow artifacts.
- Phase 30: tiny live read-only account and project monitor.
- Phase 31: controlled second tiny live dry-run and stricter one-attempt gate.
- Phase 32: release freeze, main merge plan, and production gap audit.
- Phase 33: human release review, tag verification, and controlled main merge package.
- Current project summary: `docs/PROJECT_PROGRESS_REPORT.md`.
