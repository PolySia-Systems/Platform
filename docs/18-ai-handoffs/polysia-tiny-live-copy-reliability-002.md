# PolySia Tiny Live Copy Reliability 002 Handoff

## Document control

| Field | Value |
|---|---|
| Review date | 2026-07-29 |
| Authorization | `POLYSIA-TINY-LIVE-COPY-002` |
| Starting `main` | `d173b8de80e322b8e33b782bb15bc937e84b5e81` |
| Working branch | `codex/tiny-live-copy-reliability-002` |
| Prior immutable run | `tiny-live-copy-20260729T054315Z` |
| Delivery evidence | Draft PR, CI, merge, deployment, and run evidence are gated later steps |

## Status

This delivery candidate implements only the verified reliability corrections
authorized for one new 12-hour Tiny Live Copy run. It does not complete Copy
Trading Stages 2 through 6, authorize general live trading, increase financial
limits, add multi-position behavior, or implement deferred scaling.

The prior run remains `FAILED_SAFE` with zero attempts, orders, fills,
positions, fees, collateral debit, or venue mutation. Its seven sanitized
artifacts and checksums were reverified read-only before this change.

## Implemented correction

The `/trades` adapter now uses route-isolated scheduling with:

- exactly 48 active aliases from the protected 102-candidate bank;
- a deterministic 30-minute circular rotation with step 34 while flat;
- 100 total `/trades` attempts per rolling 10 seconds;
- 80 discovery attempts and 20 reserved attempts per rolling 10 seconds;
- at most four `/trades` calls in flight;
- evenly spread discovery and `/positions` baseline reads;
- retries and recovery probes charged to the same budgets;
- integer and HTTP-date `Retry-After`, clamped to 1–60 seconds;
- bounded `1, 2, 4, 8, 16, 30` second fallback with deterministic jitter;
- one shared cooldown circuit and one recovery probe.

While flat, 120 continuous seconds of `/trades` unavailability finalizes as
`INCONCLUSIVE_DATA_SOURCE`. With exposure, discovery remains disabled and
authenticated follower management continues; a public 429 alone does not
trigger emergency cancel-all.

The active loop now performs kill-switch and follower management,
authenticated reconciliation, and required market checks before selected
leader polling. All-candidate discovery remains off while the single capacity
slot is occupied.

## Market-time correction

Strict BTC 15-minute mapping now derives interval start from
`btc-updown-15m-<epoch>`, verifies it against the Gamma child market's
`eventStartTime`, and verifies child `endDate = start + 900 seconds`, with at
most one second of representation tolerance. Gamma `startDate` is treated only
as listing metadata and is no longer compared with the interval start.

Four sanitized real regression fixtures from the failed run reach the corrected
time gate. Exact slug, condition, token, outcome, and adjacent-interval
rejections remain fail-closed.

## Persistence and reports

Additive SQLite state persists:

- discovery ordering version, cursor, active aliases, subset digest, and
  rotation timestamp;
- outage start, next probe, cooldown attempt, and last source success;
- per-alias read windows and pagination checkpoints;
- normalized pending events without source addresses or transaction hashes.

Checkpoint advancement and pending event staging are atomic. Seen-event and
leader-inventory updates are also atomic, so restart replay cannot duplicate a
position transition. Reports add authorization, active-window, request-rate,
cooldown, source-availability, market-time, and management-priority evidence.

The initial ordering is aliases that produced sanitized events in the failed
run, sorted by alias, followed by the remaining stable aliases. No profitability
or unreviewed scoring is used.

## Safety invariants

Unchanged controls include:

- maximum three venue entry attempts and three completed cycles;
- maximum USD 5 entry debit and USD 10 cumulative experiment entry cost;
- one pending entry, one position, and one related exit;
- ten-second signal age, post-only entry, minimum size, partial-fill handling,
  take profit, and leader-close behavior;
- Strategy to Risk to Execution to Polymarket Adapter;
- geoblock, kill switch, acknowledgement, allowance, reconciliation,
  ambiguity, redaction, and duplicate-prevention gates;
- no stop-loss, averaging, hedge, martingale, funding, transfer, bridge,
  wallet creation, or allowance increase.

Preflight verifies emergency cancellation readiness without creating a test
order and must produce zero venue mutation.

## Validation and delivery gates

Focused deterministic tests cover pacing, rolling budgets, route isolation,
four-call concurrency, `Retry-After`, fallback, shared circuit/probe behavior,
flat and active outage policies, four market-time fixtures, rotation coverage,
capacity priority, durable restart state, unfilled-attempt recovery,
sanitization, and checksums.

The final local suite passed 586 tests after the durability review. Compile,
edited-file format, lint, typing, dependency, secret-scan, build, OSV, SBOM,
Compose-config, diff, encoding, and protected-input gates also passed. The
local Docker daemon was unavailable, so the required container build remains a
CI gate. No PR, CI, merge, deployment, or live-run success is claimed by this
handoff.

## Rollback and remaining status

Before launch, revert the focused commit and rebuild the previous image. The
new SQLite tables are additive. After launch, preserve SQLite state and reports;
never roll back while exposure exists without an explicit containment plan.

Future scaling remains deferred. Stages 2 through 6 remain incomplete. One
authorized run is not evidence of profitability, repeatability, or production
readiness.
