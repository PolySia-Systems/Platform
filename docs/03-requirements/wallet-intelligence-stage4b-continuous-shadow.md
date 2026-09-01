# Wallet Intelligence Stage 4B — Continuous Shadow Portfolio v0.2

- **Status:** IMPLEMENTED; deployment evidence is recorded separately
- **Mode:** `DATA_ONLY` / Shadow only
- **External mutation:** official public GET reads and protected local SQLite writes only
- **No authority:** no signal, order intent, Risk approval, order, cancellation, signature,
  transfer, account mutation, or Live authorization

## Goal

Stage 4B turns the immutable Stage 4A windows into one durable forward experiment.
It measures copyability continuously without double-counting overlapping polls or
resetting inventory at every run. Stage 4A schema v1, history, current pointers,
commands, and ten-minute timer remain unchanged as an independent comparison and
recovery dataset.

```text
Stage 3 Alpha + Stress
  -> protected canonical wallet union
  -> official Polymarket trades and verified metadata
  -> global first-seen event journal
  -> independent per-wallet portfolios
  -> one shared-capital PolySia follower portfolio
  -> durable fills, fees, positions, attribution, ledger, marks, and settlement
  -> cumulative address-free health and results
```

This is a bounded experimental Shadow portfolio inside the modular monolith. It
does not implement or claim the generalized production portfolio, OMS, ledger,
capital allocator, execution router, or strategy orchestrator described as TARGET
architecture elsewhere.

## Experiment identity and lifecycle

Every experiment has an immutable `experiment_id` and records:

- policy, cost-model, and synthetic-bankroll versions;
- the complete validated capital and polling configuration;
- the Stage 3 selection version at start and on every poll;
- the source snapshot, feature set, policy, ranking, publication time, protected
  membership, and deterministic selection digest;
- `RUNNING -> DRAINING -> FINALIZED` lifecycle timestamps.

`RUNNING` accepts verified buys and sells. `DRAINING` rejects new buys but keeps
polling retained wallets for sells, marks, and settlement. `FINALIZED` is allowed
only with zero open synthetic positions and cannot be polled. A changed runtime
configuration cannot silently continue an existing experiment.

## Event journal and incremental polling

- `event_id` is globally unique in the Stage 4B journal.
- Only first-seen events are evaluated. Overlap and replay increment duplicate
  evidence but never repeat a fill or ledger entry.
- A durable watermark advances only in the same transaction that publishes the
  poll, journal, evaluations, portfolios, positions, attribution, ledger, and marks.
- The default one-minute poll overlaps its last watermark by 30 seconds. A missed
  interval catches up from the prior watermark; Stage 4A continues its independent
  ten-minute windowed run.
- One fenced SQLite lease prevents concurrent Stage 4B publishers. An abandoned
  poll is marked failed and prior durable state remains authoritative.

## Portfolio layers and capital controls

Each selected wallet receives an independent synthetic bankroll. The combined
follower has a separate shared bankroll and enforces maximum event, leader,
market, total-exposure, cash, and position-count limits. The follower keeps
per-leader position attribution, so one leader cannot sell another leader's
synthetic inventory.

Opposite outcomes in the same market are rejected as conflicting exposure.
Executable depth is consumed once within each counterfactual portfolio scope;
all leaders share one depth budget in the combined follower. Partial fills are
recorded when they satisfy the official minimum order size. Missing or stale
evidence is `UNKNOWN`; capital and conflict decisions are `REJECTED`.

Alpha, Stress, overlap, and exit-only retained evidence remain distinguishable as
`ALPHA`, `STRESS`, `ALPHA_STRESS`, and `RETAINED_EXIT_ONLY`.

## Fees, latency, liquidity, and valuation

Stage 4B does not use Stage 4A's flat configured fee. It requires the official
market-specific `feeSchedule`. For a verified taker schedule it calculates:

```text
fee = shares * fee_rate * (price * (1 - price)) ** exponent
```

and rounds to the venue's five-decimal fee precision. Disabled schedules produce
a verified zero. A missing, incomplete, non-taker, or invalid schedule produces
`UNKNOWN` and no synthetic fill.

Every evaluation separates source/API lag, post-observation signal delay, leader
to follower price movement, half-spread cost, depth impact, fee, unavailable
liquidity, and quote timestamp. Current positions mark at a fresh executable bid;
when a refresh is unavailable, the last known good mark is retained and health
warns rather than inventing a price.

The external contract was rechecked on 2026-08-25 against official Polymarket
[fees](https://docs.polymarket.com/trading/fees),
[rate limits](https://docs.polymarket.com/api-reference/rate-limits),
[user trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets),
and [batch order books](https://docs.polymarket.com/api-reference/market-data/get-order-books-request-body).

## Decimal accounting and settlement

Cash, quantity, cost basis, fees, P&L, exposure, and NAV use `Decimal`. Every fill
or settlement writes signed cash, quantity, cost-basis, realized-P&L, and fee
deltas. The health check reconstructs current balances from ledger strings using
`Decimal`; it does not aggregate money through binary floating point.

The cumulative identity is:

```text
NAV = initial_cash + realized_pnl + unrealized_pnl - fees
```

Settlement is accepted only when official market metadata says the market is
closed and supplies one complete, exact outcome set with one `$1` winner and all
other outcomes `$0`. Ambiguous prices never close a position.

## Health, recovery, and retention

Health is tied to the configured poll interval and reports cumulative events,
evaluations, overlap/replay duplicates, zero-or-nonzero duplicate processing,
unknown ratio, unknown fee provenance, marks, open positions, verified-closed
settlement backlog, lifecycle, and Decimal ledger consistency. Critical
staleness, duplicate processing, unbalanced accounting, or a finalized
experiment with positions fails closed.

Operational health publication is downstream of the atomic poll transaction. A
temporary SQLite lock or artifact-write failure during that publication cannot
invalidate a successful poll or terminate the persistent worker. The existing
atomic artifact remains last-known-good, while the interval output records a
sanitized `health_refresh` category and stage. Settlement backlog age measures
the current uninterrupted nonzero-backlog episode, not the most recent poll.
The persistent service initializes each storage boundary once per process. A
transient SQLite lock during initialization, lease acquisition, state loading,
poll persistence, lease release, or health publication is classified at that
exact boundary; the current attempt is skipped safely and the normal interval
retries without terminating the worker.
Transient source-unavailable and market-read failures use the same bounded
persistent-loop retry behavior. Persistence, lease-integrity, and unexpected
failures remain fail-closed and may terminate the worker for systemd recovery.

Schema v5 is standalone in `continuous-shadow.sqlite3`. Stage 4B is its only
runtime writer; maintenance migration or restore may write only while the worker
is explicitly stopped. Stages 1–4A remain in `wallet-intelligence.sqlite3` and
cannot block Stage 4B's financial transaction. Telemetry remains in its existing
sidecar. The application uses a short read-only Stage 3 transaction followed by
an atomic local snapshot; it does not use `ATTACH` or a cross-database transaction.

The current selection is last-known-good input. If source reading fails, the
local snapshot is reused. If its publication time exceeds the default 36-hour
versioned freshness policy, Stage 4B records `STALE`, rejects BUY/new exposure,
and continues exits, marks, and settlement. A fresh later snapshot restores
normal RUNNING behavior without changing the experiment identity.

Offline extraction from combined schema v4 preserves all financial and audit
state, validates counts, integrity, foreign keys, provenance, and Decimal ledger
identity, and initializes a fresh local lease/fencing epoch. Both database files
have independent checksummed backup and disposable restore validation. A failed
source, market, quote, calculation, or transaction records a safe poll failure
without advancing the watermark or replacing last-known-good state.

Rollback before the first schema-v5 mutation may restore the cutover checkpoint.
After schema v5 progresses, the old combined state must never be resumed silently:
both files are preserved and the operator explicitly restores the checkpoint or
abandons the post-cutover Shadow interval. Encrypted off-host backup remains an
operational gap when no approved destination exists.

`portfolio-results` reports first/latest event evidence, event-level outcome
counts, explicit duplicate-processing evidence, follower and per-wallet state,
separate Alpha and Stress counterfactuals, close outcomes, settlement counts,
latency and execution-cost distributions, interval-aware health, and explicit
confidence limitations. Pool overlap is visible and deliberately included in
both selected pool views; it is never hidden inside a combined-only number.
If an open position has no executable bid, its cost basis remains explicit but
NAV and total P&L are labelled partial instead of inventing a mark or presenting
an incomplete valuation as reconciled.

## Acceptance criteria

- Stage 4A schema and behavior remain unchanged.
- Stage 4A and Stage 4B use separate SQLite files and can write concurrently
  without file-lock contention.
- Stage 4B records an atomic, versioned selection snapshot and is the only
  runtime writer of its financial database.
- A stale or temporarily unavailable source selection never creates new
  exposure; exits, marks, and settlement continue from local last-known-good state.
- Restart and overlapping polls cannot duplicate events, fills, fees, or ledger entries.
- Stage 4A overlap or operational-report contention cannot terminate the Stage
  4B worker; transient SQLite-busy failures retain durable prior state and are
  retried only on the next normal poll interval.
- Cross-run sells use persistent inventory and verified settlements close positions.
- Independent wallets, the labeled mixed baseline follower, and separate Alpha
  and Stress followers produce distinguishable evidence.
- CLOSE and SETTLEMENT ledger rows retain Wallet, Pool, market, and event
  attribution.
- Rolling 1h/6h/24h unknown ratios are reported separately from initialization
  backlog.
- Compose and systemd force `DATA_ONLY` and `LIVE_TRADING_ENABLED=false`.
- The persistent worker has no order authority.
- Shared follower liquidity is consumed once and supports deterministic partial fills.
- Fee provenance is market-specific or `UNKNOWN`; no flat 2% assumption is used.
- Accounting identity and signed ledger reconstruction are Decimal-consistent.
- Failure keeps last known good state; migration, both backups, real restores,
  restart, and no-state-fork rollback evidence pass.
- No Stage 4B domain or application module imports Risk, Execution, strategy,
  wallet, signing, cancellation, or trading-authority code.
