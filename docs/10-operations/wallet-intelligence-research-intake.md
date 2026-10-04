# Wallet Intelligence research intake

CURRENT: a Platform-owned, read-only adapter and application research policy for
the independent **Wallet Intelligence** producer. This is separate from existing
candidate synchronization, copyability selection and SHADOW_ALPHA admission.
The producer remains `wallet_intelligence` / `wallet-intelligence` /
`WALLET_INTELLIGENCE_`; Platform retains its own `polysia` package and CLI.

## Contract and ownership

Input: the producer's public `wallet-intelligence/v1` JSON, profile
`research-candidates/v1`, feature set `descriptive/v1`. The adapter reads at most
8 MiB, validates required types, identities, counts, ranks, UTC ordering, candidate
support, source windows, components and the analytical SHA-256 digest. Duplicate
JSON keys and nonfinite values are rejected. Digests omit `snapshot_digest` and
`diagnostics`, using sorted UTF-8 JSON with compact separators. Monetary values
remain decimal strings, with `Decimal` at the application boundary.

Canonical producer revision for this integration:
`ff856037b979d9d6e6af1380f31fbac4c1cb77f8`, draft
[Wallet-Intelligence PR 1](https://github.com/PolySia-Systems/Wallet-Intelligence/pull/1).
The [public contract](https://github.com/PolySia-Systems/Wallet-Intelligence/blob/ff856037b979d9d6e6af1380f31fbac4c1cb77f8/docs/contracts/wallet-intelligence.md)
and [consumer mapping](https://github.com/PolySia-Systems/Wallet-Intelligence/blob/ff856037b979d9d6e6af1380f31fbac4c1cb77f8/docs/contracts/platform-consumer.md)
own the reviewed input meaning. The exact plan is producer-owned and unchanged.
No producer internals, Python runtime dependency or SQLite access is introduced.

The adapter translates into venue-neutral research publication/record types.
The source analytical JSON and complete source records remain intact, including
additive fields, capabilities, profile/ranking versions, original board ranks,
features, labels, composition cards, evidence depth, source references and coverage.
Protected account identity has its own field; it is never injected into metrics.
Producer cohort rank is neither board rank nor Platform `source_score`.

## Run and inspect

```powershell
polysia wallet-intelligence intake --artifact <wallet-intelligence.json> --output <research-report.json>
polysia wallet-intelligence intake --artifact <wallet-intelligence.json> --allow-partial
polysia wallet-intelligence intake --artifact <wallet-intelligence.json> --require-copyability
polysia wallet-intelligence intake --artifact <wallet-intelligence.json> --include-identities
```

The command performs bounded local reads and optional atomic local report writes.
It does not acquire provider data, connect to an account, initialize runtime stores,
change selection pools or invoke Risk/Execution. No environment setting or source
default changes. The report is `wallet-intelligence-research-intake/v1`, a consumer
projection rather than a republished producer artifact.

Default output masks protected account addresses even when repeated in names,
provenance URLs or messages. Stable `wallet_ref` hashes preserve traceability and
ordered producer candidate references. `--include-identities` exposes the intact
source-record projection in the explicitly requested local report. Condition IDs
and evidence/body digests are not treated as account identities. The original
artifact remains the authority for digest verification; redacted reports cannot
replace it.

## Policy and failure behavior

- CANDIDATE with supported valid fresh evidence becomes ACCEPTED for descriptive
  research. WATCHLIST remains WATCHLIST; EXCLUDED/DATA_HOLD become REJECTED with
  source and consumer reasons. There is no count padding or readiness score.
- Snapshot and record expiry are checked against actual consumer UTC. Publication
  times from the future are rejected. Original source times never become fresh
  simply because a file was read or replayed.
- PARTIAL requires explicit `--allow-partial`. Its original status, unread counts
  and missing partitions are preserved. COMPLETE_FOR_SCOPE never means all users.
- A valid empty publication yields ACCEPTED_EMPTY and can atomically replace an
  earlier research report. Invalid, stale, disallowed partial or missing-capability
  input exits 2 and preserves an existing output file. A rejected projection remains
  observable on stdout; safe schema/read errors use stderr. No source file can be
  overwritten by `--output`.
- `--require-copyability` rejects this producer's NOT_EVALUATED capability. No
  `source_score`, `copy_backtest_pnl`, `r20_pnl`, `r20_wr`, `copy_loss_rate` or
  `r20_slip` is synthesized. Report admission remains NOT_ASSESSED / NOT_ADMITTED.
  Follower-size/delay/fee/liquidity evidence and the existing independent admission,
  capacity and execution gates remain necessary before any trading or SHADOW_ALPHA
  use. Research acceptance has no execution authority.

## Acceptance and usability

Synthetic contract tests exercise the full CLI -> adapter -> application path,
protected projections, null/zero, versions, malformed/tampered input, empty,
partial, stale, unsupported capabilities, atomic failure and source preservation.
Existing candidate-provider and CLI/architecture tests remain required.

The actual Prompt 1 artifact is also consumed through this command at real UTC,
with its exact file/digest/revision and output recorded in the local cumulative
`artifacts/wallet-intelligence-integration/implementation-receipt.json`. AC-15 is
established by that real boundary evidence, not solely by the synthetic fixture.
AC-01..AC-14 reuse the verified producer evidence; AC-16 adds the Platform checks,
hosted CI and deliberate final review.

Baseline: board hints alone lacked supported activity/windows/freshness and could
not be expressed as truthful empty/partial intake through the old candidate type.
Improvement demonstrated here is traceable descriptive research usability and
explicit missing-capability rejection. Predictive, profitability, scale and trading
benefit remain unproved.

## Disable and rollback

Stop invoking `wallet-intelligence intake`; no timer or automatic consumer was
installed. Existing candidate sources and defaults continue unchanged. Roll back
this optional command/adapter revision if needed; no database migration is required.
Keep immutable producer artifacts with their original expiry. Producer implementation
should be reviewed/merged before the integration that consumes its contract; both
PRs remain drafts in this delivery. No merge, deployment or trading was performed.
