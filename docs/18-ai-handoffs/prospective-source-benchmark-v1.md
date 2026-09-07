# Prospective source benchmark v1

- **Status:** RESEARCH EVIDENCE; not Live authorization
- **Recorded:** 2026-09-07
- **Window:** 600 seconds public read-only
- **Run ID:** `94e2d0748145493eb28f80a03f272ece`
- **Interval:** `VALID` / `closed`
- **Code label at measurement:** `working-tree` on `codex/prospective-evidence-collector`

This record is sanitized. Raw SQLite and JSON stay under `artifacts/` and are
not in Git. No wallet addresses, credentials, or Live path were used.

A first 608-second window was discarded: newest-first REST pages inflated
`LATE`/`GAP`. The numbers below are the corrected 600-second window after
ascending source-time emission. Quiet REST wallets are not treated as sequenced
gaps.

## Candidates

| Candidate | Kind | Wallet identity | Status | Samples | Accepted |
|---|---|---|---|---|---|
| `rest_activity` | REST `/activity` poll (baseline) | yes, hashed alias | MEASURED | 300 | 21 |
| `rest_trades` | REST `/trades` poll | yes, hashed alias | MEASURED | 303 | 21 |
| `clob_market_ws` | official CLOB market WebSocket | no | MEASURED | 7359 | 7359 |
| `clob_user_ws` | official CLOB user WebSocket | would be yes | UNAVAILABLE | — | credentials required; not searched |

Followed public aliases: 3. Market tokens streamed: 8. Drain errors: 0.

## Latency (exact sample counts)

Receive→normalize uses a monotonic clock. Source→observe is wall-clock and
counted only for events with source time inside the window.

| Source | Normalize n | P50 | P95 | P99 | In-window source→observe n | P50 |
|---|---|---|---|---|---|---|
| `rest_activity` | 38 | 1_049_064_900 ns | 1_049_064_900 ns | 1_049_064_900 ns | 1 | 4_577_058_000 ns |
| `rest_trades` | 38 | 681_138_200 ns | 813_178_800 ns | 813_178_800 ns | 1 | 3_236_419_000 ns |
| `clob_market_ws` | 7359 | 1000 ns | 1700 ns | 2500 ns | 7355 | 375_774_000 ns |

Wallet REST normalize latency is poll HTTP time, not a streaming hop.
In-window wallet lag has **n=1**. That is insufficient to rank REST sources
on freshness.

## Integrity

| Source | Duplicate | Late | Conflict | Reverted | Unattributable | Incomplete | Gap | Overload |
|---|---|---|---|---|---|---|---|---|
| `rest_activity` | 0 | 17 | 0 | 0 | 0 | 262 | 0 | 0 |
| `rest_trades` | 0 | 17 | 0 | 0 | 0 | 265 | 0 | 0 |
| `clob_market_ws` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Coverage versus the wallet-identity union: both REST sources `1`.
Reconnect counts: 0. Market-state freshness when a wallet event arrived:
**0 of 42** matched a streamed token (`UNKNOWN`). Market WebSocket does not
supply wallet identity.

## Selection

- Best public REST wallet source in this window: `rest_trades` (integrity
  tied, coverage tied, lower poll normalize latency).
- `fast_wallet_stream_qualified`: **false**. No unauthenticated
  wallet-attributable stream exists. Official user WebSocket stays
  `UNAVAILABLE`.
- Lowest market-stream latency must not be compared with wallet attribution.

Same-observation replay digests (Current Control vs Target Exposure v1) differ
as required: Control may accumulate; Target Exposure v1 does not.
`unknown_count=0` in this recorded accepted set. This is not Alpha.

## Confidence

**Medium for source inventory, low for REST freshness ranking.** One 10-minute
public window, three discovered wallets, one in-window wallet lag sample, and
no wallet-token overlap with the streamed market set. Do not invent a fast
wallet winner.
