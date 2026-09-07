# Prospective Research Evidence Collector

- **Status:** IMPLEMENTED as DATA_ONLY research capability; not deployed
- **Mode:** public read-only collection and local replay
- **External mutation:** none
- **No authority:** no Live, Risk, Execution, wallet, or order path

## Goal

Benchmark public real-time sources, collect a typed canonical observation
stream, and prove restart-safe replay against Target Exposure v1 before any
exact-SHA DATA_ONLY deployment.

This requirement does not prove profitability, Alpha, or Live readiness.

## Sources

Wallet-attributable and market-state latencies are measured separately. A
market WebSocket is never treated as a wallet identity source.

| Candidate | Kind | Public? | Role |
|---|---|---|---|
| `rest_activity` | wallet event | yes | current REST `/activity` poll baseline |
| `rest_trades` | wallet event | yes | second official REST `/trades` poll |
| `clob_market_ws` | market state | yes | official CLOB market WebSocket |
| `clob_user_ws` | wallet event | no | UNAVAILABLE; authenticated credentials are required and are not searched |

No more than two wallet-attributable candidates are compared. Lowest
normalize latency alone does not win. Attribution, recovery, and integrity
are mandatory. Insufficient samples stay `INSUFFICIENT`. Credential-gated
sources stay `UNAVAILABLE`.

## Canonical event

Schema `research-evidence-v2` separates the source trade identity from each
wallet-attributed observation identity. Two wallets observing the same source
trade therefore remain distinct evidence while retaining a shared
`source_event_id`. The schema also preserves market and outcome references,
side, price, size, source time, observed time, hashed leader alias,
confirmation/reversion, classification, and sanitized provenance. UTC wall
clocks are persisted. Durations use monotonic clocks. Existing v1 stores are
migrated additively; no research evidence is deleted or relabeled. Legacy v1
rows remain readable but cannot recover wallet observations that were already
collapsed before migration, so new comparative research must use v2 capture.

Classifications: `ACCEPTED`, `DUPLICATE`, `LATE`, `CONFLICTING`, `REVERTED`,
`UNATTRIBUTABLE`, `INCOMPLETE`, `GAP`, `OVERLOAD`.

## Collector

The collector is provider-neutral. Venue translation stays in adapters.

- Single-writer isolated SQLite (`research-evidence.sqlite3`)
- Dedup across retries and restarts
- Initial snapshot, reconnect, and explicit gap/backfill recovery
- Bounded queue; overload invalidates the experiment interval
- Missing decision evidence invalidates the interval instead of inventing a
  favorable value
- Decisions record evidence IDs, code SHA, configuration digest, and policy
  version
- Diagnostic transport errors may fail open as incomplete control events
- Reports are sanitized; wallet addresses never appear

Do not write research evidence into the Stage 4B financial database or the
latency sidecar. No cross-database transactions.

## Replay

Current Control and Target Exposure v1 consume the same accepted observations.
Replay is chronological by observed time and keeps independent episode state
for each Portfolio x Market x Outcome. Admission requires an explicit,
side-aware executable quote observed no later than the wallet observation,
with available quantity and recorded fee. A leader trade price is never
substituted for follower execution evidence. Missing attribution, books,
prices, fees, marks, or gaps remain `UNKNOWN`.

Leader markouts use source event time. Follower-actionable markouts use local
observed time. Both use stored 5s / 30s / 5m snapshots, select the earliest
qualifying snapshot deterministically, and never interpolate prices.

This is not a second accounting engine. Stage 4B ledger semantics remain in
the historical replay path.

## Later research capture

Wallet+Market research needs accepted wallet-attributable trades plus
event-time market snapshots at decision and markout horizons. Market-only
research needs market-state evidence without using wallet fills as labels.
Neither is implemented as an Alpha contest here.

## CLI

```text
python -m polysia.cli research source-benchmark --duration-seconds 600
python -m polysia.cli research prospective-replay --database artifacts/research-evidence.sqlite3 --run-id <id>
```

Raw benchmark databases stay under `artifacts/` and are not committed.
Official comparison windows are 10–20 minutes. The command is public
read-only and opt-in; ordinary pytest does not use the network.

Sanitized measurement evidence:
[prospective-source-benchmark-v1](../18-ai-handoffs/prospective-source-benchmark-v1.md).
