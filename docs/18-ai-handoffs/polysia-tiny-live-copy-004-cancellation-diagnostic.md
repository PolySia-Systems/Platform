# PolySia Tiny Live Copy 004 Cancellation Diagnostic Handoff

## Document control

| Field | Verified value |
|---|---|
| Review date | 2026-08-01 |
| Source and deployed commit | `62342fee801aa2fabffa6fd78a728e2ce5b7279d` |
| Runtime run ID | `tiny-live-copy-20260801T003600Z` |
| Authorization ID | `POLYSIA-TINY-LIVE-COPY-004` |
| Final classification | `FAILED_SAFE` |
| Live authorization status | Consumed and terminal; no restart or replacement run is authorized |

This handoff is the sanitized local continuation record for the fourth bounded
Tiny Live Copy authorization. It records read-only diagnostic evidence gathered
after the worker stopped. No retry, replacement, cancellation, account
mutation, deployment, or new Live run was performed during the diagnostic.

## Executive outcome

The exact authorized commit passed preflight and started one healthy worker with
102 unique protected candidates. The worker observed 70 events and accepted two
fresh signals for detailed evaluation. The first signal became stale at the
final pre-submit check and caused no venue mutation. The second signal passed
the final check and created one accepted Post-only entry order.

The order received no fill during its 90-second operational lifetime. At the
cancellation deadline, the worker issued a cancellation request, but the
immediate authenticated open-order confirmation still returned the order. The
worker therefore stopped `FAILED_SAFE` with the durable Attempt and capacity
preserved as ambiguous. The final emergency cleanup read found no open orders,
so no additional cancellation was required.

Subsequent authenticated read-only checks proved:

- zero open orders;
- zero confirmed fill size for the submitted order;
- zero active tradable positions and zero nonzero exposure;
- zero completed cycles and zero cumulative experiment entry cost.

The account is currently flat. The run must not be restarted because its
authorization and Entry Attempt are consumed.

## Market and signal evidence

The submitted signal targeted the Polymarket BTC 15-minute market:

```text
Bitcoin Up or Down - August 1, 4:30AM-4:45AM ET
btc-updown-15m-1785573000
Outcome: Up
```

The official market later resolved `Up`. Resolution did not create follower
profit because the follower order never filled.

The two relevant source events were observed together from one protected
candidate alias:

1. A `Down` OPEN/BUY event executed at `08:27:39Z`. It passed the initial check
   but reached approximately `10.034` seconds of age at the final check, about
   34 milliseconds beyond the unchanged ten-second gate. It was rejected
   locally without consuming an Attempt.
2. An `Up` OPEN/BUY event executed at `08:27:42Z`. Its final submission age was
   approximately `8.475` seconds, so it remained eligible.

The final `Up` order evidence was:

| Field | Verified value |
|---|---:|
| Best Bid | `0.52` |
| Best Ask | `0.53` |
| Post-only entry price | `0.49` |
| Quantity | `5` |
| Maximum debit including expected fee | `2.53746` USDC |
| Confirmed fill size | `0` |
| Actual experiment entry cost | `0` USDC |

Because the BUY price was below the final Best Ask, the repaired local
Post-only check correctly classified it as non-crossing. The venue accepted the
order, which proves that this run did not repeat the previous Post-only crossing
rejection.

## Cancellation timeline and diagnosis

| Event | UTC timestamp |
|---|---|
| Final pre-submit recheck passed and Attempt claimed | `2026-08-01T08:27:50.475955Z` |
| Operational cancellation deadline | `2026-08-01T08:29:20.475422Z` |
| Durable fail-safe update | `2026-08-01T08:29:22.208367Z` |

The runtime calls `cancel_order` and then immediately calls `get_open_orders`
once. That confirmation still showed the order, causing:

```text
TinyLiveCopyError: order cancellation was not confirmed
```

The later final cleanup read found no open orders and recorded
`not_needed_no_open_orders`. Current authenticated reads also show no open order
and no fill. The narrowest evidence-supported diagnosis is a cancellation
confirmation timing or consistency gap between the cancellation request and
the immediate open-order read. The exact venue-side transition cannot be
proven from retained evidence.

An authenticated terminal order-detail read is currently unavailable because
the SDK rejected the returned `OpenOrder` response shape as an SDK contract
mismatch. This prevents claiming an exact venue terminal status even though
independent open-order, trade, and position reads prove the account is flat.

## Safety and retained-state findings

- Exactly one venue Entry Attempt was consumed.
- No fourth Attempt is possible under the existing durable cap.
- No Fill, exit order, fee, P&L, completed cycle, or nonzero exposure exists.
- The worker exited without restart; no second worker or replacement run was
  created.
- The durable run remains `FAILED_SAFE` and conservatively retains ambiguous
  entry state. Do not alter it without a separately reviewed reconciliation
  procedure.
- All seven sanitized run-artifact checksums verified.
- Exact candidate wallet addresses do not appear in the sanitized run
  artifacts or this handoff.
- The protected runtime candidate file was not automatically deleted because
  the run retained ambiguous internal order state. It remains server-local and
  access-restricted; manual cleanup was not performed during this read-only
  diagnostic.

## Bounded correction recommendation

Do not start another Live run yet. Implement and validate only the smallest
coherent repair:

1. Add a bounded authenticated read-only confirmation window after a cancel
   request instead of relying on one immediate open-order read.
2. Continue only when open-order, account-trade, and position evidence proves
   zero order and zero fill; otherwise preserve the existing fail-closed stop.
3. Add deterministic regression coverage for a cancellation that is visible on
   the first read and absent on a later bounded read, plus persistent ambiguity
   and delayed-fill cases.
4. Repair or adapt the official SDK `OpenOrder` response contract with contract
   tests before relying on the terminal order-detail endpoint.
5. Reconcile the consumed run's durable ambiguous state and delete the protected
   candidate input only through an explicitly reviewed maintenance procedure.

Any future Live run requires regression, full relevant gates, isolated
zero-mutation Shadow, exact commit deployment, a new Run ID, and a separate
owner authorization.

## Evidence-retention warning

This repository handoff is a sanitized summary, not a complete backup of the
runtime evidence. Do not decommission or erase the server until the following
have been copied to independent protected storage and verified:

- every Tiny Live Copy report directory and checksum file;
- the current SQLite database and verified backups;
- deployment identity and image/commit evidence;
- protected operational configuration needed for audit or recovery, excluding
  secrets from ordinary repository storage.

Deleting the server after creating only this handoff would preserve the main
conclusions but would lose raw diagnostic, database, and audit evidence.

## Local owner archive

Four separately authorized Tiny Live Copy experiments (`001` through `004`)
have been run. On 2026-08-02, two verified SQLite snapshots and all 67 server
report files were downloaded and verified under the owner-local, untracked
directory:

```text
C:\Users\Siamak\Documents\PolySia-Server-Archive\2026-08-02
```

The protected 102-unique-wallet runtime input is stored adjacent to that dated
directory as `POLYSIA_COPYTRADING_WALLETS_102.txt`. It is intentionally outside
the repository and must never be committed, logged, or copied into a report.
See `C:\Users\Siamak\Documents\PolySia-Server-Archive\ARCHIVE-NOTE.md` for the
local evidence index and verification summary.
