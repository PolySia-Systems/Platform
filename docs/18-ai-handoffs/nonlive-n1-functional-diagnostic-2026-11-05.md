# N1-F: bounded native functional diagnostic

Date: 2026-11-05. Status: **DIAGNOSTIC COMPLETE; SUSTAINED TRIAL BLOCKED**.
This is dated evidence, not live host truth or a new campaign authorization.

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
