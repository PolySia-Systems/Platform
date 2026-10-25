# Retained research artifact intake

CURRENT: Platform's internal read-only artifact adapter and application research
policy validate retained descriptive research JSON. This path is separate from
native candidate synchronization, copyability selection and SHADOW_ALPHA admission.
It reads an explicitly supplied local file and requires no other application,
source acquisition, private repository or additional runtime environment.

## Input contract and ownership

Accepted input uses schema `wallet-intelligence/v1`, profile
`research-candidates/v1` and feature set `descriptive/v1`. Platform's validator and
contract tests own the accepted interface. The adapter reads at most 8 MiB and
validates types, identities, counts, ranks, UTC ordering, candidate support,
source windows, components and the analytical SHA-256 digest. Duplicate JSON keys
and nonfinite values are rejected. Digests omit `snapshot_digest` and
`diagnostics`, using sorted UTF-8 JSON with compact separators. Monetary values
remain decimal strings, with `Decimal` at the application boundary.

The adapter translates into venue-neutral research publication/record types.
Original analytical JSON, source records, candidate order, versioned fields,
labels, source references and coverage remain intact. Protected account identity
has its own field and is never injected into metrics. Input candidate rank is
neither board rank nor Platform `source_score`.

## Run and inspect

```powershell
polysia wallet-intelligence intake --artifact <retained-research.json> --output <research-report.json>
polysia wallet-intelligence intake --artifact <retained-research.json> --allow-partial
polysia wallet-intelligence intake --artifact <retained-research.json> --require-copyability
polysia wallet-intelligence intake --artifact <retained-research.json> --include-identities
```

These are commands in Platform's own `polysia` package. They perform bounded local
reads and optional atomic report writes. They do not acquire provider data,
connect to an account, initialize runtime stores, change selection pools or invoke
Risk/Execution. No environment setting or source default changes. The output
schema is `wallet-intelligence-research-intake/v1`; it is a consumer projection,
not a replacement for the input artifact.

Default output masks protected account addresses, including occurrences in names,
provenance URLs or messages. Stable `wallet_ref` hashes preserve traceability and
ordered candidate references. `--include-identities` exposes the intact source
record projection only in the explicitly requested local report. Condition IDs
and evidence/body digests are not treated as account identities. A redacted report
cannot replace its source artifact for digest verification.

## Policy and failure behavior

- CANDIDATE with supported valid fresh evidence becomes ACCEPTED for descriptive
  research. WATCHLIST remains WATCHLIST; EXCLUDED/DATA_HOLD become REJECTED with
  source and consumer reasons. There is no count padding or readiness score.
- Snapshot and record expiry are checked against actual consumer UTC. Future
  publication times are rejected; reading or replaying never refreshes source time.
- PARTIAL requires explicit `--allow-partial`. Original status, unread counts and
  missing partitions are preserved. COMPLETE_FOR_SCOPE is limited to stated scope.
- A valid empty artifact yields ACCEPTED_EMPTY and can atomically replace a report.
  Invalid, stale, disallowed partial or missing-capability input exits 2 and
  preserves any existing output file. Rejection remains observable on stdout;
  safe schema/read errors use stderr. `--output` cannot overwrite the input file.
- `--require-copyability` rejects NOT_EVALUATED capability. No `source_score`,
  `copy_backtest_pnl`, `r20_pnl`, `r20_wr`, `copy_loss_rate` or `r20_slip` is
  synthesized. Admission remains NOT_ASSESSED / NOT_ADMITTED. Independent follower,
  capacity, risk and execution evidence is still required before trading or
  SHADOW_ALPHA use. Research acceptance has no execution authority.

## Validation and operation

Deterministic CLI, adapter and application tests cover protected projections,
null/zero, versions, malformed/tampered input, empty/partial/stale cases,
unsupported capabilities, atomic failure and input preservation. Existing native
candidate sources and defaults remain unchanged. This file-reading command
installs no timer or service and requires no database migration. Stop invoking
it to disable this optional workflow; retain original artifact identities and
expiry whenever replay is required. Descriptive intake demonstrates no predictive,
profitability, capacity or trading benefit.
