# PolySia Tiny Live Copy Diagnostic Handoff

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-29 |
| Source-of-truth branch | `main` |
| Source and deployed commit | `92e7746e983dcc5f77ea49a57017f2243fdd0a26` |
| Implementation PRs | `#38`, `#39` |
| Runtime run ID | `tiny-live-copy-20260729T054315Z` |
| Final classification | `FAILED_SAFE` |
| External mutation | None |
| Live authorization status | Previous run consumed; a new run requires new explicit owner authorization |

This handoff is the durable continuation record for the first bounded Tiny Live
Copy runtime attempt and its read-only diagnostic. It supersedes chat history
as the source for the facts below. The implementation handoff
[`polysia-tiny-live-copy-experiment.md`](polysia-tiny-live-copy-experiment.md)
remains authoritative for the approved experiment design.

## Executive outcome

The exact merged `main` commit was deployed to the controlled Helsinki host.
The 12-hour worker started with 102 protected candidate aliases and passed its
startup safety gates. It then failed safely during public-data monitoring after
the Polymarket Data API returned HTTP 429.

No order was submitted. There was no fill, position, fee, collateral debit,
cancel, replacement, or other venue mutation. Durable attempt and completed
cycle counters remained zero, cumulative entry cost remained zero, and the
starting and final account balances were identical.

The failure exposed two independent implementation issues:

1. the discovery request schedule can exceed a safe share of the official
   `/trades` rate limit and its retry behavior does not honor server guidance;
2. valid BTC 15-minute signals are rejected because Gamma `startDate` is
   treated as the market interval start even though it is a listing timestamp.

The diagnostic is complete. The experiment is not complete, and another live
run is not authorized by the prior authorization.

## Verified runtime evidence

The run produced the expected sanitized evidence set under the protected server
report directory:

```text
status.json
summary.json
decisions.jsonl
orderbook_snapshots.jsonl
sanitized_events.jsonl
checkpoint.json
checksum.sha256
```

All recorded checksums verified. The final runtime and SQLite records agree on:

- state and classification `FAILED_SAFE`;
- stop reason `PolymarketCopyTradingSourceError: Public API returned HTTP 429`;
- 102 candidate aliases;
- 25 newly observed public events;
- 46 repeated observations removed by deduplication;
- four fresh candidate signals;
- zero venue entry attempts;
- zero completed live cycles;
- zero cumulative entry cost;
- no current entry order, exit order, fill, or position;
- protected candidate input deleted after the worker exited;
- emergency cancellation not required because no order existed;
- authenticated WebSocket, geoblock, and startup controls passed.

The experiment container exited normally after recording the fail-safe result.
The existing read-only PolySia monitor and unrelated server services were not
disturbed.

## HTTP 429 diagnosis

The failing request was:

```text
GET https://data-api.polymarket.com/trades
```

The current worker polls 102 aliases on a six-second cycle. Ignoring pagination
and retries, this requests approximately:

```text
102 / 6 * 10 = 170 requests per 10 seconds
```

The official endpoint limit is 200 requests per 10 seconds and is enforced per
IP using a sliding window. The process-local limiter allows 140 requests per 10
seconds, but it pauses and releases bursts rather than evenly pacing calls.
Pagination, retries, other API consumers on the same IP, and sliding-window
effects remove the remaining margin.

Current retry behavior is one retry after a fixed 0.25-second delay. It does not
parse `Retry-After`, use exponential backoff or jitter, coordinate a global
endpoint cooldown, or preserve response headers and timing telemetry. The
reported `api_errors=0` is not evidence that public source calls succeeded; that
counter covers only a narrower authenticated cleanup path.

Exact response headers, response body, first-429 timestamp, successful request
count before throttling, and effective retry concurrency are unknown because
the current transport does not preserve them.

## Market-time mapping diagnosis

Four fresh BTC Up/Down 15-minute `OPEN` events passed event freshness and
identity checks but were rejected with:

```text
market start/end metadata mapping failed
```

For these markets, the epoch embedded in the canonical slug equals Gamma
`eventStartTime`. Gamma `endDate` equals that interval start plus 15 minutes.
Gamma `startDate` was approximately one day earlier and represents listing or
creation time, not the trading interval start.

The installed SDK exposes Gamma `startDate` as its market `start_date` and does
not expose `eventStartTime`. The current mapping therefore compares different
semantics and rejects valid markets.

The correct strict mapping is:

- derive interval start from the canonical slug epoch;
- verify it against the Gamma child market's `eventStartTime`;
- verify Gamma `endDate` equals interval start plus 15 minutes;
- retain exact slug, condition, token, and outcome identity checks;
- retain the one-second representation tolerance;
- do not broaden freshness or time tolerances;
- do not use Gamma `startDate` or date-only `endDateIso` as interval bounds.

Fixing this mapping would allow these events to reach later book, fee, Risk, and
Execution gates. It does not prove that any would result in an order.

## Runtime-priority and restart findings

The worker already stops broad discovery while an entry, position, or exit is
active. However, it polls the selected leader's public `/trades` feed before
managing the follower's authenticated order and position. A public HTTP 429 can
therefore delay higher-priority follower management.

The required priority order is:

1. kill switch and emergency controls;
2. active follower order and position management;
3. authenticated reconciliation;
4. selected-leader monitoring;
5. new-signal discovery;
6. baseline and optional enrichment.

Durable SQLite state protects venue-attempt accounting, event identity,
position state, and duplicate submission. Per-alias page checkpoints and the
last poll time are currently process-local. A restart reconstructs them with a
20-second overlap, but an outage longer than that could miss selected-leader
close history. Persist those read checkpoints before relying on restart
recovery for a longer experiment.

## Recommended bounded correction

Keep all financial, safety, and strategy controls unchanged:

- maximum USD 10 cumulative experiment entry cost;
- maximum USD 5 debit per entry;
- maximum three entry attempts and three completed cycles;
- one follower order or position at a time;
- 5% entry offset and 10% take-profit;
- ten-second signal freshness;
- Risk authority, geoblock, kill switch, authorization, persistence,
  reconciliation, redaction, and duplicate prevention.

Implement only the reliability corrections:

1. Add endpoint-level request telemetry without response bodies or sensitive
   data.
2. Evenly pace `/trades` discovery below a documented internal budget.
3. On the first 429, open one global `/trades` circuit, pause discovery, honor a
   valid `Retry-After`, otherwise use bounded exponential backoff with
   deterministic jitter, and permit only a single recovery probe.
4. Continue authenticated management of any existing follower order or
   position during a public-data cooldown; never create a new signal from stale
   leader data.
5. Correct market interval mapping using slug epoch, Gamma
   `eventStartTime`, and Gamma `endDate`.
6. Persist the per-alias read checkpoint and last successful observation time.
7. Add focused deterministic tests for 429 pacing/backoff/circuit recovery,
   priority ordering, restart checkpoints, and market-time semantics.

At a six-second cycle, theoretical endpoint capacity is 120 aliases. A 70%
share is 84 aliases and a 50% share is 60 aliases. The conservative diagnostic
recommendation is an internal `/trades` budget of 100 requests per 10 seconds,
reserve 20 for recovery and selected-leader monitoring, and use up to 48 active
discovery aliases while retaining the protected bank of 102. Subset selection
and the maximum continuous recovery window remain owner decisions and must be
documented before another live run.

## Exact recommended next task

> Continue from synchronized `main` and read the root `AGENTS.md`,
> `docs/00-governance/PROJECT_STATUS.md`, and
> `docs/18-ai-handoffs/polysia-tiny-live-copy-diagnostic-handoff.md`.
> Implement only the verified Tiny Live Copy reliability corrections for
> endpoint-aware pacing and 429 recovery, active-position priority, strict
> Gamma `eventStartTime` market mapping, and durable read checkpoints. Preserve
> all financial, Risk, Execution, geoblock, kill-switch, authorization,
> redaction, freshness, attempt, and cycle controls. Add focused deterministic
> tests, run the required repository validation once, create a Draft PR, wait
> for CI, review, squash-merge, synchronize `main`, and deploy only read-only
> verification. Do not start another live run. Stop and request a new explicit
> owner authorization after reporting the verified deployment state and the
> proposed active candidate subset and recovery window.

## Continuation rules

- Do not repeat the migration, architecture audit, server deployment audit,
  Stage 1 discovery, or this diagnostic.
- Do not interpret the failed-safe run as a strategy-performance result.
- Do not increase signal age, financial caps, attempts, cycles, or
  concurrency to make a run proceed.
- Do not reuse the consumed authorization or run identifier.
- Do not start another live run without a new persistent authorization
  identifier and explicit owner approval for that exact run.
