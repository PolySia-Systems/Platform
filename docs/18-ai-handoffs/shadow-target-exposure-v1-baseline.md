# Shadow Target Exposure v1 historical baseline

- **Status:** RESEARCH EVIDENCE; not Live authorization
- **Backup:** `helsinki-final-20260906T175930Z` (local, read-only)
- **Recorded:** 2026-09-07
- **Experiment:** `71e7622c8a6e472f847d212b78099903`
- **Policy / cost model / bankroll:** `continuous-shadow-policy-v0.2` /
  `polymarket-fee-depth-delay-v0.2` / `synthetic-bankroll-v0.2`
- **Schema:** 6
- **Cutoff:** `2026-09-06T18:00:11.947824Z`

This record preserves sanitized numbers from the immutable backup. It does not
contain databases, wallet addresses, or secrets. The Helsinki host is not a
runtime dependency.

## File SHA-256 (verified before and after read-only use)

| File | SHA-256 |
|---|---|
| `continuous-shadow.sqlite3` | `7505496e4fd3cc2dd9860720899c860b272649dcbd969d558c9263c69c14406e` |
| `wallet-intelligence.sqlite3` | `16b80a19b61cc830dc1d31d45a4b71ba3ff8c75f09dfffd3e805192222bd33fc` |
| `wallet-intelligence-latency.sqlite3` | `dcb652c35012c4a2095f6d4915cc23d802137df3cb426658d65de7aac8521462` |

Integrity check `ok`. Alpha Ledger Decimal identities balance. Dataset digest
`6530984a8f7c1abc3d61dbe41b9f11fbdbc6d6358271a4ab8d23246057f1308a`.

## 450 versus 455

Authoritative frozen Alpha `SIMULATED` fills in this snapshot are **450**
distinct events, all with journal rows and executable follower prices.
**455** is a later live query after this 18:01Z backup and is not this
baseline. OPEN 154 + INCREASE 255 + REDUCE 11 + CLOSE 30 = 450 simulated
fills. SETTLEMENT 119 has null `event_id`.

## Authoritative Alpha snapshot (Current Control)

| Field | Value |
|---|---|
| Initial cash | 1000 |
| Cash | 575.4218960966089783672484173 |
| Realized P&L | -208.0059589036773680327515830 |
| Unrealized P&L | -27.7897158983581094414885426 |
| Fees | 60.95329 |
| NAV | 703.2510351979645225257598747 |
| High-water NAV | 1000 |
| Drawdown | 0.2967489648020354774742401253 |
| Exposure / locked | 155.6188549997136536000000000 |
| Open positions | 15 |
| Distinct wallets (count only) | 55 |

Current-Control stateful Replay reproduced cash, fees, realized P&L, exposure,
open quantity, open position count, unrealized P&L, and NAV within the Decimal
tolerance. Parity: **passed**.

## Data-sufficiency matrix

| Capability | Class |
|---|---|
| Exact Current-Control reconstruction | SUPPORTED |
| Target Exposure reconstruction | PARTIAL |
| Market Confirmation | PARTIAL |
| Sub-second latency scenarios | UNSUPPORTED |
| Leader/follower Markouts | UNSUPPORTED |
| Conditional Wallet+Market vs Market-state-only | UNSUPPORTED |
| True independent Market-only | UNSUPPORTED |
| Follower-native exits | PARTIAL |
| Structural Alpha | UNSUPPORTED |

Target Exposure is PARTIAL because later increase order books are not stored
and settlement rows have no `event_id`. Missing marks stay UNKNOWN.

## Primary comparison (descriptive, not a promotion result)

Both sides used the same 569 Alpha ledger events, starting capital 1000,
recorded executable prices, Stage 4B fees/exits/settlement, and the same
cutoff. SignalArbiter is not a probability model. The report-time fill filter
is descriptive/non-stateful and was not this Replay.

| Metric | Current Control | Target Exposure v1 |
|---|---|---|
| Marked NAV | 703.2510351979645225257598748 | UNKNOWN (1 open mark missing) |
| Book NAV (cash + cost) | 731.0407510963226319672484173 | 987.7182051856597972393690003 |
| Cash | 575.4218960966089783672484173 | 908.1991099595359177489059687 |
| Realized P&L | -208.0059589036773680327515830 | 6.797354632381460775243831131 |
| Unrealized P&L | -27.78971589835810944148854252 | UNKNOWN |
| Fees | 60.95329 | 19.07914944672166353587483074 |
| Exposure / locked | 155.6188549997136536000000000 | 79.51909522612387949046303161 |
| Open positions | 15 | 16 |
| Turnover | 3656.422433530121099330919125 | 1293.304450549290443639413521 |
| Admitted first buys | 154 | 147 |
| Skipped repeat / rebalance / re-entry | 0 / 0 / 0 | 181 / 40 / 40 |
| Completed episodes | 130 | 131 |
| Expectancy / completed episode | -0.7828500467287866002462314746 | 0.05188820330062183797896054311 |
| Profit Factor | 0.8498865459832801884428511540 | 1.029148464444179423054729415 |
| Replay digest | `e37f40e97eeea82dba17b94497c46952044c13351b4eb8bc8ce8914224243a91` | `154b81c5e06f908acc06ed525a987247b3efe5a0e48dceb2f38b1d924d658b54` |

Classification: **insufficient_marks_not_an_alpha_result**. Target Exposure
reduced turnover, fees, and locked capital on this PARTIAL Replay. One
UNKNOWN open mark blocks a marked-NAV claim. Positive reconstructed realized
P&L is not out-of-sample Alpha, not Market-only Alpha, and not Live readiness.
Do not treat fills as independent observations.

## Claims that remain false

- Profitability
- Out-of-sample evidence
- Independent Market-only Alpha
- Live or production readiness
- A deployed real-time path
