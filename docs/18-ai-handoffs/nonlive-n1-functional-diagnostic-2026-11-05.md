# N1-F: bounded native functional diagnostic

Date: 2026-11-05. Status: **DIAGNOSTIC COMPLETE; SUSTAINED TRIAL BLOCKED**.
This is dated evidence, not live host truth or a new campaign authorization.
The N1-F2 continuation below establishes a later prospective functional result;
it does not change the closed N1-F or failed sustained N1 verdicts.

## Decision and provenance

No deployed implementation defect was demonstrated. Public activity/trade reads,
normalization and identity-cache equivalence worked on the selected control.
The retained wallet supplied no activity in the tested windows. The complete
current native journal/evaluation/virtual-fill/Console route remains
**NOT_EXERCISED**: the captured control's selected market had closed before its
eligibility check, its book returned HTTP 404, and one final current window for
that same control was complete empty. No replacement control, forced admission,
backdated experiment or further search was used to obtain a pass.

Recommendation: **resolve the fresh eligible-workload prerequisite before a new
sustained trial**. Obtain prospective complete activity for an explicitly
assessed cohort, current mapping/fees/two-sided book and a correctly handled
post-start native event. A current rejection proves only its rejection branch;
a virtual fill still needs separate evidence. No production repair or deployment
is warranted by this sample. This diagnostic is finished; there is no further
scheduled wait, hourly model review or new 48-hour run.

- Repository baseline: `c19561fd21ac416ab03676f2b61ef11928f87dd9`, clean `main`.
- Final executable source remains
  `783954f9c9fb1ffef3905c2536f503df71f3f43b`; baseline differs only in the two
  existing N1 documentation files. No source, dependency, configuration or schema
  change was made. This delivery changes documentation only, on
  `codex/n1-functional-evidence`; its protected PR owns final Git/CI identity.
- Installed image:
  `sha256:12dff8e3cae85e8e9e8dcecb0ac1d73271ee4dc30ade92a83c423482b724639d`.
  Existing [PR #251](https://github.com/PolySia-Systems/Platform/pull/251)
  explains the readiness repair; [PR #253](https://github.com/PolySia-Systems/Platform/pull/253)
  owns the previous terminal review.
- Helsinki and independently fenced Nuremberg were accessed through the existing
  pinned SSH aliases. Diagnostic containers used the installed image, public GET
  transport, one request at a time, no credentials, no production-state/config
  mounts, `DATA_ONLY` and `LIVE_TRADING_ENABLED=false`.

## Frozen scope, usage and closure

Separate policy: `owner-n1f-diagnostic-20261105`, digest
`0bc46f285b6068269fe55453c65ac67e40247ce088f935a000bd60d45720e69f`.
Frozen start **08:52:18.753662 UTC**, expiry **10:52:18.753662 UTC**;
first request **08:52:26.754230 UTC**, last **09:07:25.145299 UTC**.
The ceiling was therefore stricter than two hours from the first request.
Closure was recorded at **09:08:44.152085 UTC**.

The shared pre-request authority capped all phases at 300 attempts / 128 MiB,
4 MiB per response, 15-second socket timeout, 9 GiB free-disk reserve,
512 MiB memory and 50% of one CPU. The tighter rolling hour capped 150 attempts /
64 MiB. The allowlist contained only Data API activity/trades/status/positions,
Gamma markets/events and CLOB book. Only two public identities were used:
unchanged original and one separately labeled positive control. One global
500-row seed was sampled; subsequent sampling of the fixed control was more than
60 seconds later. No position endpoint, authenticated endpoint or financial
mutation was requested.

Final diagnostic usage: **18 attempts, 4,626,777 accounted bytes**. Seventeen
successful responses contain **432,473 measured bytes**. The book HTTP 404 has
unknown body cost and retains its full **4,194,304-byte reservation**; the one
unsettled reservation was neither refunded nor called zero uncertainty. Unused
282 requests / 129,590,951 bytes confer no permission to resume the closed scope.
STOP is durable; the diagnostic directory and spent database were made
root-owned and unwritable by the container UID. No diagnostic container or
scheduler remains running.

Original N1 remains unchanged: STOP, OS restart fence, inactive
`polysia-platform-worker.timer`, **454 requests / 66,678,249 bytes / uncertainty 0**,
**9 virtual positions / 148 journal events / 296 evaluations / 22 ledger rows**.
Frozen original plan SHA-256 remains
`4f46710daa78d78d1647132842f347ceba356dcd3c4d7b95cc2890288b7f1d92`.
The old single grant, failed verdict, inventory and two-hour/48-hour requirements
were not changed. `LIVE_NOT_AUTHORIZED / NOT_PERFORMED` applies throughout.

## Cause discrimination and contract checks

| Hypothesis | Discriminating evidence | Result and limit |
|---|---|---|
| Identity, UTC or filter error | Original address recovered from the retained cohort and exact failed request; normalized identity, epoch-second bounds and encoded public filters inspected | No demonstrated construction error. Public proxy-wallet fields agree for the control; independent original EOA/funder ownership or chain history was not proven. |
| Broad provider outage | Successful paired public reads and `/v2/status` | Not supported at capture. Snapshot age 15 s, serving lag 1 s, activity projection age 0 s and worst ingestion cursor lag 1 block. This is aggregate evidence, not independent chain or per-wallet proof. |
| Normal retained-wallet inactivity | Complete original five-minute and one-hour activity/trades windows are empty while the control yields four matching occurrences | Supports missing current workload. Does not prove lifetime inactivity or the cause of every historical empty response. |
| Parser/mapping defect | Identical raw control trades replayed through shipped uncached, cold-cache and warm-cache adapters | Four normalized unique events, zero filtered/rejected/duplicate rows in every mode; equal normalized hash. No demonstrated defect in this sample. |
| Eligibility/workload coupling | Current closed market/book 404; complete-empty final control window; offline lifecycle characterization | Activity presence does not establish executable eligibility. Native selection expiry can block the whole admitted composition; idle time supplies no useful qualification credit. |

Official contracts checked: [account activity](https://docs.polymarket.com/api-reference/feeds/list-account-activity),
[public trades](https://docs.polymarket.com/api-reference/feeds/list-trades) and
[data freshness](https://docs.polymarket.com/api-reference/service/get-data-freshness).
The current trades default minimum is **0.01 TOKENS**, not the older assumed
100 USD; zero does not remove that documented minimum. All four control sizes
exceed it. `taker_only=false` includes maker-side rows. Wallet-bound trade time
bounds and activity bounds are inclusive; the global seed ignores those bounds,
so its timestamps were checked locally. Both APIs share provider infrastructure.

The global seed's newest row was 223 seconds old at the frozen cutoff, but the
subsequent wallet-bound control response included a later trade only seven
seconds before that cutoff. Seed age is therefore not a measured universal
publication lag. Its latest trade was observed about 9.584 seconds after execution;
these four observation-minus-execution delays include unknown upstream publication
and transport components, not independently measured venue-publication latency.

## Paired results and raw provenance

All pairs used `limit=500`; activity used `type=TRADE`, trades used
`taker_only=false`. Each walk completed in one page. Counts compare canonical
trade occurrences, not row text. Each paired row below spent two requests.

| Identity / interval, UTC | Activity unique / bytes | Trades unique / bytes | Intersection / differences |
|---|---:|---:|---:|
| Original, Nov 5 08:47:26–08:52:26 | 0 / 85 | 0 / 85 | 0 / 0 |
| Original failed interval re-query, Nov 4 10:24:05–10:29:05 | 0 / 85 | 0 / 85 | 0 / 0 |
| Original wider interval, Nov 5 07:52:26–08:52:26 | 0 / 85 | 0 / 85 | 0 / 0 |
| Separate control, Nov 5 08:47:26–08:52:26 | 4 / 3,215 | 4 / 3,076 | 4 / 0 |

The final fixed-control activity query at 09:07:25 covered its then-current
five-minute window: complete, zero rows, 85 bytes, one request. No second seed or
new control was chosen. The original historical interval re-query is later
evidence; it does not establish what was served at the original instant.

Key raw SHA-256 values:

- Original empty activity/trades envelope:
  `dbdb95442e84297edbcab6bac994095604db25f8ab06e41ea11d4637d519e917`.
- Control activity:
  `b9d78b9f6a9a9ad5790068ef7deaa259c1d058d97048fe58fb5757ab2c3dbce2`.
- Control trades:
  `513a7241befa1f32927bd17af77da7495cfbfdfb8b5e707be7f2e7ae7713c33f`.
- Equal normalized-event serialization across all three adapters:
  `3d2e983a9b64f2f8e557a66dd86860c19c0a1ccce47deb966826fd9d59c938b3`.

Successful HTTP latency observations ranged **45–241 ms** across 17 responses;
the original recent pair was 156/123 ms and control pair 216/163 ms
(activity/trades). The failed book response took 81 ms. This small sample is not
sustained throughput, percentile capacity or a trading-performance estimate.

## Functional trace, optimization and policy boundaries

Actual captured input traversed bounded reservation -> retained raw/hash -> v2
complete envelope -> four canonical occurrences -> exact Gamma identity mapping
-> four normalized events. The primary replay was repeated with `--network none`
using the installed artifact and original execution/observation timestamps.
It reproduced every serialized event exactly. The first offline harness blocked
asyncio's own local socket setup; the corrected harness retained OS network
isolation and denied outbound connection creation. Both invocation logs remain
preserved. This was a harness correction, not a product change.

| Compatible source mode, same recorded trade payload | Real Gamma requests | Real Gamma bytes | Measured adapter duration |
|---|---:|---:|---:|
| Existing uncached event lookup | 2 | 14,120 | 222.416 ms |
| Existing exact identity cache, cold | 2 | 11,501 | 255.136 ms |
| Existing exact identity cache, new source/cache instance warm | 0 | 0 | 1.799 ms |

Cold exact lookup saved **2,619 wire bytes** with no request-count saving and was
slower in this sample. Warm restart recorded two cache hits, zero misses/errors
and avoided both identity requests. Timings include a replayed Data API payload;
they are not full live poll latency. Mutable market status, fees, resolution and
books remain uncached. No sustained cache hit rate or total worker cost saving
is claimed.

Current eligibility used the shipped `verify_native_eligibility` and
`BoundedMarketAdapter`. Its selected market ended at 08:55 UTC; the 09:01 check
found it closed/not accepting orders and got book HTTP 404. Benchmark sequencing
allowed this short market to expire; that does not demonstrate a provider outage
or establish that a timely preflight would also fail. The final fixed-control
current window was empty. Thus no genuinely eligible prospective experiment was
started, no recorded pre-start event became fresh credit, and current source
journal -> evaluation -> virtual accounting -> Console projection remains
**NOT_EXERCISED**. A current virtual fill was not established.

Existing deterministic native composition tests exercise allowed fills,
rejections, stale/incomplete source, duplicate input, restart, report projection,
open inventory, closure reserves, STOP and uncertain/limited authority. Two
additional isolated synthetic-clock characterizations demonstrated:

1. Quiet revalidation at three hours preserves original eligibility age and open
   inventory; subsequent fresh activity refreshes the same session without
   duplicate accounting.
2. A mixed active/quiet two-wallet cohort does not refresh as a whole. At four
   hours its RUNNING composition blocks before financial advancement, even
   though one candidate has activity. This is a current conservative admission
   boundary, not proof that the active wallet is broken. DRAINING close-only
   handling remains separately covered and requires current per-action evidence.

No expired timestamp was refreshed merely for receiving a healthy empty page.
Observation/diagnostics may describe healthy idle input; they cannot authorize
new exposure. Any future per-wallet entry isolation or broader monitoring policy
needs prospective versioning/review. No frozen acceptance criterion was relaxed.
The old useful-evaluation gap conflates opportunity supply with processing
progress: classify these observations as **healthy public input / missing
workload**, the expired control as **ineligible market**, and the HTTP failure as
**charged source failure**. A processing hang was not demonstrated. Useful
observation hours remain zero.

## Verification, storage and recovery

Executed on unchanged executable baseline, Python 3.14.7:

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/adapters/test_polymarket_copytrading_source.py tests/unit/adapters/test_native_discovery.py tests/unit/storage/test_acquisition_authority.py tests/integration/test_native_platform_lifecycle.py tests/integration/test_native_drain_transport.py tests/integration/test_continuous_shadow_portfolio.py
139 passed in 142.57s
.venv/Scripts/python.exe -m pytest -q artifacts/n1f-20261105/test_policy_characterization.py
2 passed in 6.24s
```

The second command is a retained isolated diagnostic, not a new tracked runtime
test module. Its exact file was also hash-verified on both hosts, SHA-256
`7662a562823078cc481bed61ef1485e4d8e72ac29e934fd64521af31cf83bcd2`.
Synthetic fixtures/clocks are not current public-input evidence.
The prior immutable full run, 2,009 passed / 33 skipped, and runtime PR/exact-main
CI 41829429646 / 41832421155 are reused for unchanged source. Full runtime,
container/browser, dependency audit and build suites were not repeated for this
documentation-only delivery; its local documentation/security checks and exact
protected CI receipt are recorded in the delivery PR.

At closure Helsinki had **23,311,183,872 free bytes**, above the 9 GiB reserve.
Container memory/CPU ceilings were enforced; no sustained CPU, RSS, telemetry
pipeline or event-load capacity measurement is claimed because no current native
poll was admitted. No private configuration or original database was mounted in
the diagnostic containers. No deployment binding or original recovery state
changed. The prior exact encrypted original spent-state recovery remains the
applicable operational evidence in the [N1 terminal record](nonlive-n1-qualification-2026-10-29.md).
That record also supplies unchanged actual private-TLS STOP, restart,
lost-reply idempotency and stale-preview/wrong-target negative-control evidence;
those consumed commissioning actions were not replayed or used to reopen N1.

Protected primary evidence root:
`/var/lib/polysia-platform/diagnostics/n1f-20261105`.
The closed capsule is `n1f-20261105-closed.tar.gz`, **142,149 bytes**, SHA-256
`e89727678663ca9ccbe243fa97a16b3ab16d21a5d7680bc34b3bc26afddc66ca`.
It contains policy, identities, raw payloads/hashes, all failure receipts,
accounting, harnesses and the network-none replay. Its 89 indexed files and
STOPped SQLite integrity/18 charged requests were independently verified from
an exact copy on fenced Nuremberg at
`/srv/polysia-platform-backups/n1f-20261105`.
This public-data diagnostic capsule is not a replacement for the separately
encrypted production recovery. Local capsule, characterization and selected
receipts are retained under ignored `artifacts/n1f-20261105/`; raw operational
material and public wallet addresses are not committed to Git.

## Required verdicts

| Verdict | Result | Scope |
|---|---|---|
| ENGINEERING | PASS | Bounded diagnosis and targeted checks complete; no demonstrated implementation repair required. |
| ADAPTER_CONTRACT | PASS | Tested v2 windows, four real normalized occurrences and identical offline replay; exhaustive real pagination not exercised. |
| SOURCE_AVAILABILITY | PASS | Successful public Data API/Gamma access and fresh aggregate status at capture; selected closed-market book was unavailable. |
| COHORT_SUITABILITY | BLOCKED | Original unsuitable for the observed workload windows; sustained suitability and historical cause remain unproven. Control is diagnostic only and currently quiet. |
| FUNCTIONAL_PATH | NOT_EXERCISED | Normalization/mapping proven; complete current prospective native journal/evaluation/fill/Console route absent. Synthetic coverage is separate. |
| SAFETY | PASS | Both scopes STOPped, old fence/counts/inventory preserved; failed request fully charged; isolated capsule independently verified. |
| INTEGRATION | NOT_REQUIRED | No executable patch; documentation uses normal protected PR integration. |
| DEPLOYMENT | NOT_REQUIRED | No proven deployed defect or artifact change. |
| READY_FOR_SUSTAINED_TRIAL | BLOCKED | Fresh eligible cohort and current prospective route are prerequisites; neither waiting nor a cache benchmark supplies them. |

No sustained-run configuration is ready to activate. The unused diagnostic
allowance and old grant cannot fund another attempt. A later owner-authorized
preflight must freeze its own scope and numerical authority, preserve the nine
retained positions separately, obtain current eligibility before ancillary
benchmarks, then measure a post-start native event before estimating a new
sustained budget. Zero admitted useful polls supplies no defensible 48-hour
throughput/cost extrapolation. The real two rolling windows and 48 useful hours,
human acceptance and financial/Live authority remain separate unmet gates.

## N1-F2 prospective native path, 2026-11-05

**PROSPECTIVE FUNCTIONAL PATH PASSED within the isolated native engine.** A real
post-start stream reached the journal, decisions, virtual ledger and authenticated
shipped Console API. No financial action occurred. This is not a sustained-run,
profitability, human-acceptance or full persistent-worker commissioning verdict.

Baseline was clean `main` at `32a1cf59fd5330067bc6c4da26e9b1e1b4cfd6c6`;
the actual run used the unchanged installed executable `783954f9c9fb1ffef3905c2536f503df71f3f43b`
and image recorded above. Task branch: `codex/n1f2-prospective-proof`.
The delivery PR owns final correction/CI/Git identity. No production release
activation, old-store transition or new campaign was performed.

### Prepared sequence and selection

Before provider I/O, the complete server runner, finite supervisor and private
Console were prepared. The stock Console and stock Caddy gateway used a separate
Unix socket and `https://localhost:9445`, a separately generated local CA and an
explicit reader role. Certificate verification succeeded; anonymous access was
401, authenticated session/report/evaluation workspace were 200. Initial gateway
validation encountered backend startup delay; it was resolved and all checks
passed **before** any provider request. Production Console/configuration and
public ingress were untouched. No authentication or role was bypassed.

The official `ISOLATED_DIAGNOSTIC` factory persists the same native service,
source, evaluator, accounting repository and reporting path as the persistent
factory. Offline constructor comparison confirmed identical configurations except
`runtime_version` and `period_duration_seconds` (one day versus unbounded). The
actual service class and `poll` method are identical. A one-day period cannot
expire within this two-hour envelope. This establishes finite-horizon engine
equivalence, **not** coverage of `native_lifecycle_poll`/`worker_tick` CONTINUOUS
admission, three-hour revalidation or long-period behavior. No fabricated
`persisted_simulations` or CONTINUOUS admission was supplied to earn this result.

Policy `owner-n1f2-prospective-20261105`, digest
`59af854a8e50f08074b91138c0c1e64666df8fc273c108d030a26a683712c15e`,
was frozen at 13:24:10.114382 UTC with expiry 15:24:10.114382 UTC. Limits:
300 attempts/128 MiB total, 150 attempts/64 MiB per rolling hour, response
4 MiB, timeout 15 s, one request in flight, cadence at least 60 s, worker
512 MiB/50% of one core and free-disk reserve 9 GiB. The earlier scope's unused
allowance was not used. The explicit budget check before starting required at
least 64 requests/64 MiB remaining; later polls required 16 requests/8 MiB.
Actual authority still reserves before every GET and owns all hard limits.

Frozen selection: at most two 500-row public seed samples, five individually
inspected identities, first eligible singleton; seed-window frequency descending,
latest timestamp descending, then normalized address. No P&L ranking. Complete
five-minute activity required at least two rows, latest age at most 60 s, valid
mapping/fees/current two-sided book and at least 300 s market lifetime remaining.
No model deliberation or benchmark intervened between preflight and startup.

One seed was sufficient; four identities were inspected, one admitted. Two
earlier candidates hit the subsecond boundary defect described below; another
had latest activity older than 60 s. Exclusions remain retained. The admitted
candidate had 101 complete activity rows, latest execution 13:29:12 UTC, verified
fees/mapping/book and active market ending 17:00 UTC. Its preflight lasted
13:29:25.451999–13:29:25.890617 UTC; prospective start was
**13:29:26.041693 UTC**, about 151 ms later. No identity was replaced after start.

### Actual prospective trace and restart

Experiment: `28294882e0934103a5b3b4a90743ed6f`.
All **32 unique journal events** executed strictly after its recorded start;
pre-start events credited: **zero**. There were **64 evaluations**, comprising
**27 SIMULATED / 33 REJECTED / 4 UNKNOWN**, and **27 ledger entries**. These are
virtual portfolio records, not 27 venue transactions: wallet portfolio 20 fills,
follower portfolio seven. Rejections retained minimum-order-size (11), capital
limit (20) and conflicting-outcome (2) reasons. Four stale-book evaluations
remained UNKNOWN; quotes were not invented or freshness thresholds lowered.

| Actual process | Poll ID | New events / duplicates | Evaluations / virtual fills |
|---|---|---:|---:|
| First worker container | `8990c2f6f62d49fd96102d22ec014a90` | 12 / 0 | 24 / 17 |
| New worker container, same durable store | `e370907e74da45dcb72d2fd17b5af0eb` | 20 / 7 | 40 / 10 |

The server automatically performed the second container invocation after the
first useful result; its due time was durable and cadence respected. Duplicate
checks confirmed unique journal IDs, unique portfolio/event evaluations and
unique ledger entry IDs across both polls. The seven overlapping occurrences
did not generate repeated accounting. No model loop controlled acquisition.

Representative linked event:
`5f1de54e22f4d6febc728c60fbc3a1ae976df8266fe49bc7d2fd0a82bfa5b4c9`.
Execution 13:29:30 UTC; first observation/first-seen 13:30:26.265644 UTC;
evaluation 13:30:30.214142 UTC; quote 13:30:22.356 UTC. Raw request
`3998d6fbfdd8428da9d532bb6925d816`, provider trace
`e97f911c7f674fcaba3c3c1ec56e95d1`, response SHA-256
`1484331e954ea9115e67589009f945e1535704da4b959e2b979916eb5a91b770`
links to its complete trade page, normalized event, current Gamma/book requests,
SIMULATED decisions and ledger postings. Detailed linked traces remain protected.

The private shipped `/api/report` and `/api/console/v1/workspace?panel=evaluate`
returned the same analytical digest:
`5c9b45b2c7f557b54930c3f73c8b5b37b7abb2131f2c1c7a9c401dae045cc18e`.
The publication identified `N1-F2_ISOLATED_DIAGNOSTIC`, actual experiment/times,
decisions, virtual balances and final STOPPED state. This is real authenticated
Console/API evidence, not a mock projection or human browser acceptance.

Final follower cash: `974.61619`; exposure: `25`; recorded fees: `0.38381`;
realized P&L: zero. Ledger balance and adjusted accounting identity delta were
zero. Total retained positions: 25 (seven follower positions); no liquidation,
fabricated settlement or reset occurred. **Valuation is incomplete**: two
follower positions had incomplete marks and reported NAV `998.359661745083...`
was explicitly `PARTIAL_OR_LAST_KNOWN_GOOD`. Posting/reconciliation success does
not establish complete current NAV or profitable performance.

### Measured limits, STOP and recovery

First request: **13:29:24.674450 UTC**; last: **13:31:36.873252 UTC**;
provider activity spanned about **132.199 s**. All **103 attempts** completed,
**1,798,565 measured/accounted response bytes**, uncertainty **zero**.
Preflight spent 8 requests/1,157,620 bytes; polls spent 37/261,242 and
58/379,703 respectively. Successful HTTP observations ranged 56–167 ms.
Endpoints: trades 3, activity 4, Gamma markets 60, CLOB book 36; no inventory,
financial-account or mutation endpoint was requested.

Native telemetry retained two real poll samples, zero errors/drops/history gap,
peak process RSS 129,212,416 bytes, maximum observed one-core CPU 40.387%, and
minimum free disk 23,298,920,448 bytes. These short samples are not sustained
capacity evidence. Container ceilings were enforced independently.

The finite systemd supervisor owned expiry, two process invocations, private
Console receipt collection and idempotent offline STOP/cleanup. It completed at
13:31:49.756531 UTC; by 13:34 all owned containers/unit were inactive, port 9445
was closed and the isolated spent authority/directory were OS write-fenced.
A network-none replay of the actual STOPped authority snapshot returned
`authority_stopped_or_mismatched` before HTTP, with usage unchanged. The actual
primary likewise remained at 103/1,798,565/0 after STOP.

Old N1 remains 454/66,678,249/0 with its nine positions and 148/296/22 records;
old N1-F remains 18/4,626,777/**1**, STOPped. Their stores, plans, old fence,
original encrypted recovery and failed verdicts were not changed.
The closed diagnostic capsule contains SQLite backup-API snapshots, raw hashes,
cohort/start, all adverse results, both polls, telemetry and actual Console
receipts. Credentials, CSRF secret and gateway private keys are excluded.
Capsule: **458,150 bytes**, SHA-256
`9d220a1267c98810a834eeff5752058116fff9377ef1030badb9c6dd7afca6a9`.
Exact contents, SQLite integrity and spent STOP/accounting were independently
verified on fenced Nuremberg. This is diagnostic recovery, not a repeated or
replacement production recovery drill. Protected roots use `n1f2-20261105`
beside their N1-F predecessors. Local evidence is under ignored
`artifacts/n1f2-20261105/`.

### Demonstrated boundary correction and validation

Two rejected preflight payloads contained 295 and 297 rows, including two rows
exactly at the integer query start. The API's whole-second start includes them,
but a fractional application lower bound puts that second's start just outside
the precise window. Native discovery/revalidation previously raised for the
entire complete response. Source-only offline replay reproduced this on the
unchanged captured bytes with an explicitly synthetic fractional replay clock.
This is a demonstrated implementation defect, not evidence of provider downtime.

The focused correction filters **only** this known lower-second encoding overlap,
retains raw coverage plus `window_filtered_rows`, and validates all remaining
rows unchanged. Whole-second inclusive boundaries remain included. Malformed,
wrong-wallet and other out-of-window rows still fail closed. Boundary-only input
is healthy quiet, supplies no fresh eligibility and still blocks at four hours;
it cannot refresh the original selection age or earn useful observation credit.
Old cohorts/stores are not rewritten. Identical captured replay now retains
293/295 in-window rows; missing uncaptured market metadata remains explicitly
ineligible. That offline replay is not additional prospective credit.

New regression tests first failed four boundary cases on the predecessor.
After correction, focused discovery/native lifecycle tests passed **35 in
28.14 s**; Ruff over the repository, compileall and mypy over both changed source
modules passed. The prior 141 checks were reused rather than rerun unchanged.
Full applicable source-change checks, immutable CI identities and integration
outcome belong to the delivery PR. The live operational proof above used the
pre-correction installed artifact; a post-correction live smoke was not performed.

Production activation is separately gated: the supported bootstrap refuses an
active pinned native session without an audited release transition. That
transition writes the original retained store, which N1-F2 explicitly forbids.
The old installation and its rollback binding therefore remain at `783954f`;
no ad-hoc admission/store edits or fence removal were used to deploy this fix.
The reviewable correction can be commissioned in a separately scoped supported
installation, or through an explicitly assessed retained-state transition.

### Seven scoped verdicts and next decision

| Verdict | Result | Scope |
|---|---|---|
| ENGINEERING | PASS | Finite runner/Console completed; reproduced boundary defect corrected with regression/replay evidence. Production activation remains gated as above. |
| INPUT_ELIGIBILITY | PASS | One explicitly admitted singleton had complete recent activity and actual current mapping/fee/book evidence; 32 later unique events were genuinely post-start. |
| PROSPECTIVE_NATIVE_PATH | PASS | Actual installed native engine, journal, evaluation and persisted continuation across two real containers. Full CONTINUOUS worker/admission and long-horizon lifecycle are not exercised. |
| VIRTUAL_ACCOUNTING | PASS | 27 real virtual postings, duplicate protection and balanced ledger; complete current valuation is not established. |
| CONSOLE_PROJECTION | PASS | Authenticated stock TLS Console report/evaluation API matches the analytical digest and stopped state; no human acceptance claimed. |
| SAFETY_AND_RECOVERY | PASS | Finite budgets/STOP/expiry, OS fencing, removed owned services, preserved old scopes and independently verified exact diagnostic capsule. |
| READY_TO_PLAN_SUSTAINED_TRIAL | PASS | Enough evidence to formulate the conditional proposal below; **not authorization or readiness to start it**. |

Next decision: review a **workload-fitting sustained plan and its commissioning
boundary**, rather than repeating this successful short run or starting 48 hours
blindly. This control had 101 trades in five minutes and 32 events over roughly
two poll minutes. Its observed rate projects beyond the unchanged 10,000-event
period cap over 50 hours; the 64 MiB period-storage cap also needs measured growth
evidence. The higher poll cost, 58 requests, would imply about 3,480 requests/hour
at one-minute cadence, far beyond this diagnostic's 150/hour envelope. Neither
increasing a grant nor idle waiting fixes the period/lifecycle constraint.

The smallest explicit draft is **NOT_AUTHORIZED / DO_NOT_ACTIVATE**:

```json
{
  "scope": "new isolated sustained trial; original scopes and inventory preserved",
  "starts_at": null,
  "maximum_duration_seconds": 181800,
  "canary_windows": {"count": 2, "seconds": 3600},
  "useful_observation_seconds": 172800,
  "safety_margin_seconds": 1800,
  "cadence_seconds": 60,
  "cohort_limit": 1,
  "maximum_requests": 220000,
  "maximum_bytes": 4294967296,
  "rolling_seconds": 3600,
  "rolling_maximum_requests": 4320,
  "rolling_maximum_bytes": 67108864,
  "maximum_response_bytes": 4194304,
  "timeout_seconds": 15,
  "memory_max_bytes": 536870912,
  "cpu_quota_percent": 50,
  "minimum_free_disk_bytes": 9663676416,
  "automatic_renewal": false,
  "activate": false
}
```

These are **proposed ceilings**, not granted authority or a reliable SLO forecast.
The larger HTTP allowance needs a new explicit owner decision; two polls cannot
establish steady-state cost. Before executable commissioning: assess a fixed
cohort whose measured event/storage growth fits the unchanged period caps, or
review a separate versioned period/lifecycle design. Do not silently replace the
control, raise period caps or reset a period to force completion. Preserve both
the old nine positions and this run's 25 virtual positions in their own scopes.

The proposal additionally requires real CONTINUOUS admission/installation
compatibility, fresh preflight, two measured rolling windows and validated rate
headroom before 48 useful hours. Three-hour revalidation and four-hour selection
expiry remain enforced; fresh complete revalidation must keep the same identities
and cannot treat quiet as renewed eligibility. A singleton avoids mixed-cohort
blocking for this proposal; adding wallets would reopen that unresolved boundary.
The existing 900-second useful-evaluation gap and all per-event freshness/Risk
rules remain unchanged. Failed freshness, depleted allowance or incompatible
revalidation must STOP and preserve inventory/evidence. No part of this draft
starts a canary, supplies elapsed-time credit, accepts human feedback or grants
financial authority. `LIVE_NOT_AUTHORIZED / NOT_PERFORMED` remains absolute.
