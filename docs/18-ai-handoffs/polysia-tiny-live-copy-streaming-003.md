# PolySia Tiny Live Copy Streaming 003 Handoff

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-07-31 |
| Starting branch and commit | `main` at `2ed6a2cc7fc9b5d9c583ccc0fc92256710a7d930` |
| Working branch | `codex/tiny-live-copy-streaming-003` |
| Prior terminal run | `tiny-live-copy-20260729T135013Z` |
| Proposed authorization | `POLYSIA-TINY-LIVE-COPY-003`, not claimed or consumed |
| Delivery state | Local validation passed; PR, CI, deployment, and Shadow remain gated |

## Verified root cause

The prior 12-hour run finalized normally with zero attempts, orders, fills,
positions, fees, collateral debit, or other venue mutation. It retained 170
sanitized BTC 15-minute trades: 33 `OPEN` and 137 `INCREASE` events.

One signal reached the process 7.525 seconds after execution. The discovery
worker awaited `asyncio.gather` for all 48 wallet reads before ingesting any
result, so the signal was not evaluated until 13.159 seconds after execution
and correctly failed the unchanged ten-second submission-age gate.

## Delivery candidate

Discovery now consumes each wallet result as its task completes. A completed
response is staged, deduplicated, evaluated, and, when eligible, reserved
without waiting for the remainder of the read batch. In-flight reads finish for
durable checkpointing, but cannot emit another executable signal once the
single slot is reserved. Active follower management remains ahead of public
leader monitoring.

A new SQLite signal-reservation record is unique per run. Reservation is atomic,
does not increment the venue-attempt counter, and is consumed in the same
transaction that claims an entry attempt immediately before submission. A
proven pre-submit rejection releases it. Restart reconciliation releases only
an orphaned reservation while the durable run remains flat and in `MONITORING`.
Ambiguous submission behavior remains fail-closed.

Signal age is checked when the event is observed, when it is evaluated, and in
the broker's `before_submit` callback immediately before the adapter call.
Sanitized reports retain executed-to-observed, observed-to-evaluation,
evaluation-to-reservation, reservation-to-submission, remaining-market-time,
and bounded batch-completion telemetry.

## Scoped market-time change

The Tiny Live Copy gate is four minutes. The shared domain functions accept an
explicit minimum while retaining their seven-minute default, so unrelated Copy
Trading paths are unchanged. The ten-second age gate, Risk authority, financial
limits, post-only behavior, 90-second cancellation TTL, 185-second SDK GTD
backstop, final-entry cutoff, geoblock, kill switch, reconciliation, pacing,
and one-order/position invariant are unchanged.

The existing cancellation and GTD constraints remain stricter than the nominal
four-minute gate. Lowering the gate alone does not permit an order that cannot
represent a safe cancellation deadline and SDK-valid expiry.

## Offline replay

The checksum-valid sanitized report was replayed read-only. Public Gamma market
metadata was used only to recover strict BTC 15-minute interval bounds from 21
unique condition IDs. All 33 `OPEN` events mapped consistently to slug epoch,
`eventStartTime`, and `endDate`.

| Measure | `10s/7m` | `10s/4m` |
|---|---:|---:|
| Fresh `OPEN` events passing the two named gates | 1 | 3 |
| Additional threshold-only events | 0 | 2 |

The two additional events had approximately 293.680 and 328.695 seconds left.
Neither can satisfy the unchanged cancellation and SDK GTD backstop. Therefore
the replay adds two threshold-only candidates but zero candidates eligible for
the complete unchanged entry-timing path. The sanitized report contains no
historical book price, spread, depth, fee, or slippage evidence for those two
events, so profitability, fill probability, and execution quality are
inconclusive.

## Focused regression evidence

Deterministic coverage includes 48 responses, a signal observed at 7.530
seconds, 47 responses completing at 13.160 seconds, evaluation before batch
completion, unchanged rejection beyond ten seconds, exact four-minute boundary
behavior, atomic concurrent reservation, no attempt consumption on reservation,
restart release, deduplication, request-circuit behavior, and follower-management
priority. The latest focused run passed 48 tests.

The full repository gate passed 592 tests plus compile, Ruff, Mypy over 128
source files, dependency checks, secret scan, package build, OSV audit, SBOM
generation, Compose parsing, and diff checks. The Windows `cyclonedx-py.exe`
wrapper returned without diagnostics; the equivalent installed module entry
point generated the SBOM successfully with exit code zero. PR, CI, container
build, deployment, and Shadow evidence remain unclaimed.

## Authorization and stop condition

Tiny Live Copy authorization is supplied through protected runtime input and
must match the independent acknowledgement. Dry-run state uses a unique
non-authorization marker. The proposed 003 authorization is not stored by
Stage 1, and no Live Run ID is claimed.

Stage 1 must stop after one exact-commit zero-mutation Shadow. Any failed,
ambiguous, or inconclusive gate blocks Live. A later Live action requires a
separate owner instruction containing the exact authorization and exact
unclaimed Run ID.
