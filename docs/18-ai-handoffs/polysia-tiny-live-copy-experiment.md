# PolySia Tiny Live Copy Experiment Handoff

## Document control

| Field | Verified value |
|---|---|
| Authorization | `POLYSIA-TINY-LIVE-COPY-001` |
| Starting commit | `a0bd5b476554f481026a156698f093fc2e57926b` |
| Working branch | `codex/copytrading-experiment` |
| Review date | 2026-07-29 |
| Runtime | CPython 3.14.6 |
| Polymarket SDK | `polymarket-client==0.2.0` |
| Delivery status | Implementation ready for PR, CI, merge, and gated deployment |

## Status declaration

This task is an explicit owner-approved exception from the inconclusive Stage
1 evidence state to one tightly bounded Tiny Live experiment. It does not
complete Copy Trading Stages 2 through 6. It does not authorize general live
trading, permanent deployment, concurrent strategies, capital scaling, or use
of candidate scores as execution authority.

## Implemented current behavior

The experiment remains inside the modular monolith:

```text
Leader public reads
-> strict normalization and stable deduplication
-> complete sizeThreshold=0 inventory baseline
-> strict BTC Up/Down 15-minute mapping
-> proven zero-to-positive OPEN policy
-> existing OrderIntent
-> independent Risk
-> existing Execution
-> Polymarket adapter
-> SQLite persistence and authenticated reconciliation
```

The candidate bank is validated and deduplicated in first-seen order, must
contain exactly 102 unique addresses, and becomes stable aliases
`candidate-001` through `candidate-102`. The raw mapping is neither tracked nor
written to reports. Runtime transfer and storage use protected standard input
and a `0600` file.

Durable SQLite state atomically consumes a venue-attempt slot immediately
before submission. Local rejection consumes none. Accepted, rejected, unknown,
unfilled, partial, and full venue outcomes consume one. Unique constraints
prevent reuse of a leader or event, and the authorization identifier is unique.
The run permits at most three attempts, three completed filled cycles, one
pending entry, one follower position, and one related exit. Confirmed entry
cost plus the maximum debit reserved for the next submission may never exceed
USD 10 across the experiment.

Entry policy uses a fresh official book, exact minimum size, Decimal
arithmetic, a 5% lower price rounded down, a USD 5 all-in debit cap, post-only
GTD, and a 90-second operational TTL. A confirmed partial fill cancels the
remainder, reconciles available inventory, and manages only that quantity. A
10% take-profit is rounded upward and submitted through Risk and Execution.

A proven leader close only triggers a bounded full FOK sell when executable
fee-adjusted follower P&L is non-negative. At negative P&L, the take-profit is
retained and the position may resolve to zero. A winning resolution is left
`REDEEMABLE` because this task does not add a redemption path.

## SDK compatibility decision

The installed SDK enforces a GTD timestamp at least 180 seconds in the future.
The owner-approved operational TTL remains 90 seconds. The worker cancels and
confirms at 90 seconds, and uses a 185-second GTD safety backstop only when it
will expire before the final-entry cutoff. Otherwise the signal is skipped.
This makes the actual eligible entry window stricter than seven minutes and
does not weaken the five-minute exclusion.

## Safety and restart

Every live activation requires:

- exact green-CI commit evidence embedded as `/opt/polysia/BUILD_COMMIT`;
- synchronized, clean server `main`;
- owner acknowledgement and LIVE flags;
- approved SDK version;
- configured signer/funder identity and signature semantics;
- passing clock, official geoblock, authenticated read, and User WebSocket;
- sufficient dedicated-account collateral for the next bounded entry;
- no unrelated open order or active, positive-value, mergeable, or ambiguous
  position;
- sufficient existing allowances without increasing them;
- kill switch inactive and emergency cancel-all available.

The Compose profile exposes no port, runs UID/GID 10001 with a read-only root
filesystem, drops all capabilities, persists SQLite and reports, and has a
heartbeat watchdog plus bounded restart. Restart reconciles counters, pending
entry, fills, position, and related exit before action. An ambiguous submission
remains consumed and fails safe without retry. Closed historical positions are
ignored only when their venue fields prove a past end date, zero current price,
zero current value, and non-mergeable status. Polymarket may still label these
zero-value records `redeemable`; that label alone is not economic exposure.
Total wallet collateral is not an experiment-spend limit.

## Evidence and reports

The run writes under `/var/lib/polysia/reports/<run-id>/`:

```text
status.json
summary.json
decisions.jsonl
orderbook_snapshots.jsonl
sanitized_events.jsonl
checkpoint.json
checksum.sha256
```

Reports include commit, run window, safe candidate counts/digest, health,
counters, sanitized attempt outcomes, latency, price difference, entry debit,
fill and exit values, fees and P&L when provable, decisions, and checksums.
Raw wallet addresses, credentials, signatures, private keys, and raw venue
order identifiers are excluded.

## Validation and reviewer focus

Focused validation covers protected candidate handling, OPEN/UNKNOWN behavior,
strict mapping, signal and market-time boundaries, price/tick/minimum-size
calculation, per-entry and cumulative cost caps, GTD compatibility,
closed-position classification, impossible take-profit,
concurrency, atomic attempt accounting, rejected/unknown submission, leader
fairness, unfilled and filled caps, partial fill, take-profit, fee-adjusted
profit/breakeven/loss and resolution, restart persistence, stale WebSocket,
heartbeat, geoblock, emergency cancellation, and no Risk/Execution bypass.

Review the attempt-claim boundary, active-order cancellation races, restart
reconciliation, resolution handling, report redaction, and the SDK GTD
compatibility rule before merge.

## Rollback and next action

Before launch, rollback is removal of the focused runtime, schema additions,
Compose profile, tests, and this handoff on the experiment branch. After launch,
do not delete SQLite state or reports. Do not stop a filled position without an
explicit manual containment plan.

Next action: create a Draft PR, obtain green required CI, review and squash
merge normally, deploy only synchronized merged `main`, run one read-only
preflight, and launch the one authorized detached experiment only if every gate
passes.
