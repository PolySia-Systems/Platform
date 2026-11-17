# Polymarket leaderboard

The private PolySia Console shows a searchable wallet bank, official trader boards,
wallet history and reference coverage. The collector and Console share a separate
SQLite evidence file. The Console opens it read-only under its existing verified
reader or operator identity. Existing trading databases and jobs have independent
scope.

## First collection and Console configuration

Use the installed release and a writable path in a private data directory.
The path's directory must already exist. Run the collector as the data owner,
using the existing job runner or an interactive terminal.

```text
polysia leaderboard refresh --database ./leaderboard.sqlite3
```

Set `leaderboard_database` in the private Console configuration to the absolute
path of that file as seen by the Console process. The runtime needs read access.
Use the existing authenticated Console entry point. Install or restart the
Console through the normal reviewed release procedure. Open **Leaderboard** in
the navigation. In hosted deployments, grant the collector write access and the
Console read access to the same private directory, including SQLite's journal
files during writes. Local Windows operators can pass an absolute Windows path
to the same CLI.

Schedule that command through the existing operator job runner at 15-minute
intervals if prompt retry is required, or at the normal six-hour cadence.
The command skips boards that succeeded within six hours. Failed or partial
boards become eligible after 15 minutes. A first manual run may use
`--force` to request an early read after the 15-minute minimum.
One SQLite lease serializes collection. It expires after 12 minutes so an
interrupted worker can recover. Use the same database path for every invocation.
Schedule configuration and host activation are release operations.

The Console reloads the current retained view automatically about once a minute
while visible on the first page. **Reload data** reads the latest retained
generation immediately. The collector owns network refresh and its budget.
The synthetic **Example** view has no access to the real wallet bank.

## Scope and fields

| Field or view | Source and interpretation |
|---|---|
| Rank, wallet and name | Polymarket Data API v2 traders board. Ties preserve the venue rank. Wallets are matched by normalized public address. |
| P&L, finite windows | Venue-reported marked net-of-flow P&L in USDC. |
| P&L, all time | Venue-reported realized lifetime P&L in USDC. |
| Volume | Provider volume in shares. |
| Rank change and history | Change from the preceding valid capture and dated observations for that same board. |
| Activity | Returned trade records and distinct markets in a seven-day window for a bounded leading-wallet sample. Incomplete reads are labelled. |
| Reference coverage | Address membership in the separately collected bank at the recorded comparison time. |

The overall day, week, month and all-time boards each have two ranking views.
The overall monthly and all-time P&L boards collect up to 1,000 rows each.
Other views collect up to 100. Monthly Sports, Politics and Crypto boards
support both rankings. The product includes the provider's combo population
where applicable. Search covers retained wallet identities. A retained wallet
can appear outside the currently selected board with its rank and values blank.

Provider numbers are projected without losing precision. Realized/open
breakdowns, ROI, win rate, copy scores and risk-adjusted returns require
separately validated definitions and histories. Profile proxy evidence is
limited to the inspected cases. Membership uses observed addresses and makes
no human-ownership inference.

Source contracts are documented by Polymarket.
[Trader leaderboard](https://docs.polymarket.com/api-reference/boards/get-the-trader-leaderboard)
and [source freshness](https://docs.polymarket.com/api-reference/service/get-data-freshness).

## Reference captures

Capture each reference you wish to compare using a public read or a verified
visible table. Import a bounded UTF-8 JSON capture with exactly these fields.
Provide real matching addresses from the capture when the scope contains rows.

```json
{
  "source": "Rivo",
  "captured_at": "2026-11-17T12:00:00Z",
  "scope": "First public leaderboard table",
  "method": "Public HTML table capture",
  "wallets": [],
  "complete": false
}
```

Accepted sources are `PolyCop`, `Rivo` and `PolyIntel`. Use an offset-aware
capture time, the exact filters and observed table bounds, and at most 5,000
unique hexadecimal addresses. Set `complete` only when the declared scope
was captured completely. Run the official collection before importing
references. An import freezes membership, count and digest of the independent
bank in its write transaction and produces a reproducible comparison. It never
admits reference members into discovery. An empty denominator or absent
official bank has no coverage percentage. Differences can reflect rank
criteria, scope, timing or missing discovery evidence. The Console displays
which addresses are shared and which are absent. Membership compares
populations and does not equate ranks or incompatible P&L.

```text
polysia leaderboard import-reference --database ./leaderboard.sqlite3 ./rivo-capture.json
```

References are refreshed separately through this import. A failed capture
leaves the previous dated comparison available. Older comparisons stay
inspectable and are marked stale after seven days. No reference credentials
are required for the official refresh.

## Failure handling and rollback

Use the collector exit code and its compact summary for job monitoring.
Repeated cursors, duplicate wallets and malformed required fields stop that
board's publication. Verified preceding pages may appear as a partial
cold-start capture. A previous complete board survives a later failure
with its original timestamp. Completed board updates are transactional per
scope. Optional activity and aggregate source-health reads do not invalidate
rank data. The Console labels a board stale after 12 hours and highlights
age after 48 hours.

A run is capped at 100 requests including retries, 50 MiB received and a
10-minute aggregate budget with per-request socket timeouts. The collector
retries transient failures within that budget. Schema and invalid parameter
failures are retained as sanitized attempt status. When rate-limit retries
are exhausted, the collector defers further official requests in that run.
Source health reports
are aggregate evidence. A board timestamp records the capture time.

The store keeps current outcomes and keeps daily normalized complete captures
for one year. Other attempts older than 30 days are pruned except for the
latest attempt of each outcome. Each capture retains mapped values, timestamps
and a digest. Full upstream response bodies are not retained by the scheduled
collector. Keep external research captures in their approved evidence directory
if exact upstream bytes are needed. Wallet discovery membership and reference
comparisons survive snapshot pruning.

To roll back, disable the leaderboard job and remove the optional path from
the next Console configuration or restore the previous verified release.
Preserve the database for a later retry or review. Copy it only with the
collector stopped or through SQLite's backup API. An existing trading database
does not require migration. No backfill or venue access is needed to inspect
retained evidence.
