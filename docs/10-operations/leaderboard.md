# Polymarket leaderboard

The private PolySia Console shows a searchable wallet bank, official trader boards,
wallet history and reference coverage. The collector and Console share a separate
SQLite evidence file. The Console opens it read-only under its existing verified
reader or operator identity. Existing trading databases and jobs have independent
scope.

## First collection and Console configuration

On releases with managed leaderboard collection, the guided installer creates
the private data directory, connects it to the Console and starts
`polysia-leaderboard-refresh.timer`. Open **Leaderboard**. The first capture
starts in the background, and an upstream outage can delay its arrival without
preventing sign-in. The timer checks every 15 minutes and the collector skips
boards that are still fresh. Inspect the last complete capture using host
admin `status`. Run the same guided setup entry with `configure --leaderboard paused`
to keep displaying retained data and stop polling, or `configure --leaderboard auto`
to resume, using the currently installed release's versioned entry.
When automatic collection is enabled, `sudo polysia-admin configure
--leaderboard-interval 120` changes the visible boards' successful refresh
interval to two hours. The accepted interval is 15–1440 minutes. Retry floors,
provider deadlines and discovery eligibility still apply.

An update from the original Helsinki setup adopts the standard data directory
and recognizes the previous manual service, timer and web override. Back up
custom units before changing them if the installer reports a conflict.

For older releases and installations without the guided host setup, configure
collection and the Console separately as described below.

## Save a wallet selection

An operator on a managed installation can select wallets across ranking pages
or searches, then choose **Save selection**. Open **Watchlists** to add the
current selection to a saved list, rename it, remove wallets or delete the list.
Watchlists are private to the signed-in operator and survive browser restarts.
Deleting a list leaves the public rankings and wallet history intact.

### Forward Shadow

Open a saved list and choose **Shadow**. Use a preset or enter your own duration
between 15 minutes and seven days. An installation runs one experiment at a
time for up to six selected wallets. Once started, the cohort and duration
are fixed. Closing the browser does not stop it. Open **View Shadow runs**
to see modeled fills, costs, coverage and realized results or stop early.
Each wallet starts with 100 virtual USDC. The model uses public order books,
caps gross notional at 5 USDC per simulated fill and charges a modeled 2% fee.
The board and this scheduler operate independently. The result reports observed
coverage rather than assuming every trade was seen. Total equity is unavailable
with open positions until a reliable closing valuation can be established.

Authorized HTTP clients can use `GET /api/console/v1/watchlists` and
`GET /api/console/v1/watchlist-runs` to read state. Use the same verified Console
login, origin and CSRF session as the browser. For writes, first read
`GET /api/console/v1/session`, retain its cookie and send `identity`, `csrf` and
the configured `Origin` with the JSON request. A watchlist write to
`POST /api/console/v1/watchlists` carries an `item` with its stable `id`, `name`,
`wallets` and expected `revision` (zero for create). Add `delete: true` to delete
that revision. Launch at `POST /api/console/v1/watchlist-runs` with a stable
32-character lowercase hex `run_id`, `list_id`, `list_revision` and
`duration_seconds`. Retry an uncertain launch with the same request ID and
inputs. Cancel at `POST /api/console/v1/watchlist-runs/cancel` using the run ID.
Each route uses the signed-in operator's own lists and runs.

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
boards become eligible after at least 15 minutes. A provider rate limit applies
to every collector using this evidence file, including forced runs and restarts.
The next eligible time respects a longer provider retry deadline. A service
error with a retry deadline defers its affected board. A manual run may use
`--force` to request an early read after the 15-minute minimum.
One SQLite lease serializes collection. It expires after 12 minutes so an
interrupted worker can recover. Use the same database path for every invocation.
Schedule configuration and host activation are release operations.

For broader wallet discovery, schedule a separate daily invocation off the
normal refresh slot. It collects up to 3,000 monthly and 3,000 all-time P&L
rows from Polymarket, typically 60 public reads. It shares the database lease
and provider cooldown, skips recent successful discovery, and leaves the visible
board depths, ranks and last successful captures intact. Discoveries become
searchable after each complete scope. Run this command after the first ordinary
collection. The default board refresh has its own six-hour cadence.

```text
polysia leaderboard refresh --discovery-only --database ./leaderboard.sqlite3
```

### Changing collection cost and coverage

Set the discovery depth and HTTP budget in the existing job command. For example,
the following collects the top 2,000 for each of the two discovery periods.
Forty full pages cover both periods. The remaining eight attempts allow for
short pages or retries within the other limits.

```text
polysia leaderboard refresh --database ./leaderboard.sqlite3 --discovery-only --discovery-depth 2000 --max-requests 48
```

| Change | Where it belongs | Proportionate check |
|---|---|---|
| Discovery depth | Set `--discovery-depth` between 1,001 and 5,000. The visible P&L boards already cover 1,000. Each depth has its own observations. Changing depth preserves the job's cadence and existing history. Omit the discovery job when the visible boards provide sufficient coverage. | Check the two completed scopes, `wallets_added`, requests and bytes. Compare several runs at the same cadence before increasing depth. |
| Request budget | Set `--max-requests` up to 100 per invocation. Allow 32 full pages for the visible boards or twice the discovery depth rounded up to pages of 100. The CLI rejects a budget below that baseline before opening the database. A fully consumed budget can leave optional details unavailable. | Check actual attempts and outcomes. Leave headroom for retries. `wallets_added` counts distinct new addresses from committed, complete scopes. A retry or an address shared by both periods does not inflate it. |
| Refresh frequency | Edit the existing scheduler. Its normal guards are six hours for visible boards and 24 hours for discovery. For example, a two-hour schedule with `--force` requests a two-hour refresh. All jobs honor the 15-minute floor and provider deadlines. Manual reference imports have their own cadence. | Verify two scheduled receipts, the retained capture times and the configured freshness objective. Ongoing stale warnings are expected if a schedule intentionally exceeds that objective. |
| Freshness warnings, retry floors, retention and hard safety ceilings | These are product or resource guarantees. Change the corresponding implementation and user-facing labels or documentation together when the guarantee changes. | Test just below and at each threshold. For retries, exercise restart and forced refresh. For retention, prove an older database keeps its current and historical evidence. |
| Ranking semantics and metrics | Period and ranking selection are existing UI controls. Changing the meaning of P&L, adding a scoring formula or changing a unit requires an explicit metric definition, compatible source data and a separately identifiable historical series when semantics differ. | Replay fixed samples with exact expected values. For a wire or UI change, regenerate the Console contract and assets and verify the affected browser journey. |

The receipt measures discovery yield for the whole invocation. A falling yield
can reflect an already populated bank. Choose depth using repeated observations
and dated reference coverage. Automatic depth changes, resumable cross-run
cursors and an IP-wide quota shared with other applications would add coordination
and recovery work. Revisit them if repeated budget exhaustion or measured
cross-job contention prevents a complete, timely collection.

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
references. A new comparison freezes the independent bank known by the reference
capture time (`first_seen <= captured_at`). Later discoveries cannot increase
historical coverage. The database records the comparison time separately in
`compared_at`. Earlier comparisons keep their original import-time bank and
digest, with a null `compared_at`. Their bank timestamp remains visible.
Reimporting a legacy capture creates an as-of-capture comparison and retains
the original record. An import never
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
