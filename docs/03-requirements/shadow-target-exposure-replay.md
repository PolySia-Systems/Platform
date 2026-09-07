# Shadow Target Exposure Replay v1

- **Status:** IMPLEMENTED as research capability; not deployed
- **Mode:** read-only historical replay
- **External mutation:** none
- **No authority:** no Live, Risk, Execution, wallet, or order path

## Goal

Freeze an immutable Stage 4B historical baseline, classify what that backup
can and cannot support, and run one pre-declared comparison:

```text
Current Control  vs  Target Exposure v1
```

This is a stateful research foundation. It does not prove profitability,
out-of-sample Alpha, independent Market-only Alpha, or Live readiness.

## Verified current behavior this requirement reuses

- Stage 4B Continuous Shadow Ledger, positions, marks, fees, and settlement.
- `SignalArbiter` as a leader-relative execution-advantage metric, not a
  calibrated probability or expected-value Alpha model.
- `CopySignalArbiterReplay` for signal-level Replay; it is not portfolio
  accounting.
- The report-time fill filter `walk_forward_policy_report` remains
  **descriptive/non-stateful**. It must not be presented as full portfolio
  Replay.

## Immutable baseline

The authoritative historical dataset is a local read-only backup. The retired
Helsinki host is not a live dependency. Databases open only as
`mode=ro&immutable=1` with `query_only`. SHA-256 values are verified before
and after analysis. Raw databases, wallet addresses, and large generated
reports stay out of Git.

Authoritative frozen Alpha SIMULATED fills on
`helsinki-final-20260906T175930Z` are **450**. A later live query of 455 is
not this snapshot.

## Data-sufficiency gate

Every research capability is `SUPPORTED`, `PARTIAL`, or `UNSUPPORTED`.
Missing evidence stays `UNKNOWN` / `INSUFFICIENT_DATA`. Order books, prices,
timestamps, liquidity, and outcomes are never interpolated. Fields created
after a decision time must not leak into that decision.

Unsupported future work stays in the matrix only: real-time source benchmark,
prospective collector, alpha-research database, Structural Scanner, Placebo
suite, sub-second latency, leader/follower markouts, true Market-only, and
deployment.

## Target Exposure v1

Policy ID `target-exposure-v1` / version `1` is frozen with the Stage 4B
cost-model version. The primary experiment changes only position construction.

| Topic | Frozen semantics |
|---|---|
| Target unit | Shares, established once from the first accepted executable price |
| Episode key | Portfolio × Market × Outcome |
| Entry / admission | Fixed account-currency entry budget equal to Current Control `maximum_event_notional` (5). Target shares = min(requested, budget / first price). Incomplete, stale, or contradictory evidence fails closed |
| Repeated signals | Additional BUY/INCREASE, including extra wallet agreement, must not increase target shares or cumulative entry budget |
| Rebalancing | A falling price must not trigger buys |
| Conflicting signals | Opposite outcomes in the same market are rejected. Gross market exposure must not exceed the current portfolio market cap (100) |
| Reduction and close | Same recorded exit evidence as Current Control, scaled to held quantity. Never sell more than held or more than recorded |
| Expiry / terminal | Settlement uses recorded settlement cash and quantity, scaled. Terminal episodes do not silently re-enter |
| Settlement | Same Stage 4B settlement semantics as Current Control |
| Re-entry | `none` |
| Dynamic sizing | Forbidden |

If Target Exposure reduces losses or drawdown but remains negative, classify it
as a Risk/Portfolio improvement, not Alpha. A PARTIAL reconstruction with
UNKNOWN marks is not a profitability result.

## Stateful Replay

Replay is chronological, deterministic, Decimal-only, and idempotent on
`entry_id`. It streams the ledger rather than loading the full database.
Current Control must reproduce cutoff cash, fees, realized P&L, exposure,
open quantity, and marked NAV from the backup before a Challenger result is
interpreted. Open positions at cutoff remain in the book. Missing reliable
marks stay UNKNOWN.

## Primary comparison

Both sides use the same source events, timestamps, starting capital,
executable-price evidence, fee/cost model, exits, settlement, and cutoff.
Fills are not independent observations. Metrics: NAV when marked, realized and
unrealized P&L, expectancy per completed Market × Outcome episode, Profit
Factor when valid, drawdown, exposure, locked capital, turnover, fees,
concentration counts, coverage, and UNKNOWN rate.

## CLI

`polysia research shadow-replay --backup-dir <read-only-backup>` writes an
optional JSON artifact outside Git. It does not deploy, restart services, or
connect this research path to Live, Risk, or Execution.
