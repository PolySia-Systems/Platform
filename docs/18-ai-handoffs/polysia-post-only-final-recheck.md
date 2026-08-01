# PolySia Post-Only Final-Recheck Handoff

## Scope and status

This handoff records the separate Post-only repair that follows merged Signal
Arbiter PR `#43`. The experimental `FULL` Arbiter remains default-off and is
not a Live authority. This task does not create or consume a new authorization
or Run ID and does not start Live execution.

## Evidence-supported diagnosis

Tiny Live Copy run `tiny-live-copy-20260731T180428Z` consumed authorization
`POLYSIA-TINY-LIVE-COPY-003` and stopped `FAILED_SAFE`. It recorded one Entry
Attempt, zero venue order identifiers, zero fills, zero completed cycles, and
zero follower exposure. The venue returned HTTP 400 with the official
Post-only crossing message.

The last persisted local order-book snapshot showed a non-crossing BUY quote,
but it preceded the venue rejection by about 1.64 seconds. The runtime then
performed safety and submission work without another book check. The exact
venue-side cause cannot be proven from retained evidence. The narrowest
evidence-supported diagnosis is a time-of-check/time-of-use gap in which the
book could change between the local snapshot and the venue POST. Retained
evidence does not prove a token, outcome, side, or complementary-price mapping
failure.

## Repair contract

- Reserve the single signal capacity atomically without consuming an Entry
  Attempt.
- Complete the existing account, geoblock, clock, stream, balance, allowance,
  and risk checks.
- Immediately before Attempt persistence, fetch a fresh market and order book,
  revalidate the exact condition, BTC 15-minute interval, binary Up/Down token
  and outcome-label mapping, ten-second signal age, four-minute market gate,
  tick size, minimum size, fees, debit cap, and Post-only price.
- Treat a BUY as locally crossing when its final price is equal to or above the
  final Best Ask. Reject only that signal, release the reservation, consume no
  Attempt, and perform no external mutation.
- Re-run independent Risk on the final intent. Persist the Attempt only after
  the final refresh and before the single venue submission.
- Dry-run executes the same final market, mapping, age, quote, and book checks
  without signing, persisting an Attempt, or submitting an order.
- Never automatically retry, reprice, replace, or convert the order after an
  external submission.

## Explicit submission outcomes

1. A local pre-submit rejection consumes no Attempt and returns to monitoring.
2. A definitive Post-only venue rejection consumes the Attempt and triggers
   bounded authenticated read-only reconciliation. Monitoring resumes only
   when there is no open order, no fill evidence, zero active tradable
   positions, and zero nonzero exposure. A second definitive Post-only
   rejection in the same Run fails safe.
3. A transport, response, or reconciliation ambiguity preserves the consumed
   Attempt and occupied durable run state, stops mutation, and fails closed.

Closed historical records are ignored only when the existing strict evidence
proves past end, zero price, zero value, and non-mergeable state. They are not
mistaken for active tradable positions or nonzero exposure.

## Validation evidence

Focused repair validation passed 90 tests plus Ruff and Mypy. A separate
Dry-run final-recheck regression passed 31 focused tests. The complete
repository suite passed 633 tests. Compileall, Ruff, Mypy, `pip check`, secret
scan, build, strict OSV dependency audit, and CycloneDX SBOM generation also
passed. Coverage includes the
official error classification, async final-refresh ordering, local crossing
without Attempt consumption, wrong final outcome mapping, the first definitive
Post-only rejection, the second same-Run rejection, ambiguous submission,
durable state transitions, the existing 7.53-second streaming regression,
true ten-second staleness, reservation atomicity, deduplication, rate limits,
and successful non-crossing Post-only submission with deterministic fakes.

Repair PR CI, final merge, single-commit deployment, additive schema
initialization, and isolated zero-mutation Shadow remain gates until separately
recorded as completed. No Live run is authorized by this handoff.
