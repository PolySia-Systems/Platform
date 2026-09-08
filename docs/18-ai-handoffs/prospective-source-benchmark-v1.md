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

The source and latency measurements above remain valid dated evidence. The
replay digests and `unknown_count=0` produced by the original implementation
are superseded: that implementation reused leader price as executable price,
shared episode state across markets, and did not separate wallet-observation
identity from source-trade identity. Schema v2 replay now fails closed without
explicit side-aware execution evidence and reports leader and follower
markouts on separate clocks. No Alpha conclusion can be drawn from this run.

## Confidence

**Medium for source inventory, low for REST freshness ranking.** One 10-minute
public window, three discovered wallets, one in-window wallet lag sample, and
no wallet-token overlap with the streamed market set. Do not invent a fast
wallet winner.

## Persistent collector operational acceptance

**PASS**, audited on the authorized Helsinki host from
`2026-09-07T22:28:52.230583Z` (T0) through
`2026-09-08T04:16:03Z`. This is DATA_ONLY durability evidence, not Alpha,
profitability, source superiority, or Live authorization.

- Deployed release and image:
  `a90fb1a8a295912265359f4d089665e6ece8e952`; rollback release
  `e1e238c381da77c0a9166db3b5f3143f9ec241a8` remained available.
- `TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`, empty Live token
  allowlist, `open_order_count=0`, and `order_submitted=null`. No mutating
  order log entry was present.
- A pre-T0 controlled restart converted the interrupted window
  `2830a78c18f74e3fbf32139de2adff74` to `INVALID_SHUTDOWN`; it was never
  relabeled `VALID`. The new run was
  `ed0a116f53164d53adcdc9763ea02ff3`.
- A consistent Backup-API snapshot at `2026-09-08T04:08:28Z` contained 33
  consecutive post-T0 `VALID` windows, one current `OPEN` window, 96,601 run
  events, and no post-T0 invalid window. Later live health reported 34 closed
  windows, `fatal=null`, `stale=false`, healthy maintenance, fresh source and
  persistence progress, and zero unexpected restarts.
- The snapshot was schema `research-evidence-v2`; checksum, isolated restore,
  `PRAGMA integrity_check`, and foreign-key validation passed. Backup SHA-256:
  `c5c3f714fadad8a890e695be24efbf63ff9f23ae072f27a636003f6c6d23c7fb`.
- Replay of the restored snapshot was byte-stable across two executions:
  report SHA-256
  `f219b32851dc067fe4360d11f9c728576f78f5fef2a715211602ba770e9738cc`,
  Control digest
  `5de74a37e1d4139e90192799b437ad0ad8d866061d102dcfabe27a66fd024724`,
  Target digest
  `dbf124a94f83a4c9a784cb665b048ec93dc4ce3feb5261c79aa8b75b1f29ebe3`,
  and 160 honestly retained `UNKNOWN` results.
- From the first post-restart snapshot (50,122,752 bytes) to the acceptance
  snapshot (104,169,472 bytes), growth was 54,046,720 bytes in 20,376 seconds:
  approximately 218.6 MiB/day. A linear seven-day pre-retention projection is
  approximately 1.54 GiB. At final audit the WAL was 0 bytes, logs remained
  under configured rotation, and 26,238,967,808 bytes of disk were available.
- `polysia-monitor-1` and `polysia-research-collector-1` were healthy with
  `RestartCount=0`. Unrelated `3x-ui` remained on its existing image, start
  time `2026-09-07T12:30:29Z`, and restart count zero. Nuremberg was not used.

The earlier `INVALID_DISK` window remains preserved as historical failure
evidence. The corrected release separates committed evidence writes from
retention/checkpoint maintenance, uses non-blocking `PASSIVE` checkpoints
outside transactions, and refreshes health during open windows. Temporary
restore and deployment-transfer artifacts were removed after verification.
