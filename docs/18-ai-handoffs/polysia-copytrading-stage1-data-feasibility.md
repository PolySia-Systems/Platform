# PolySia Copy Trading Stage 1 Data Feasibility

## Document control

| Field | Verified value |
|---|---|
| Task | Stage 1 — Data Feasibility |
| Review date | 2026-07-28 |
| Starting commit | `e15c8beb60cafb40052a212446b7bb2fa5857ad7` |
| Working branch | `codex/copytrading-experiment` |
| Runtime environment | Existing Conda environment `PolySia` |
| Python | CPython 3.14.6 |
| SDK inspected | `polymarket-client==0.2.0` |
| Decision | `NO_GO` for Stage 2 |

## Outcome

The official public Polymarket Data API can expose executed trades for a public
User Profile / Proxy Wallet with the fields needed to construct a
venue-neutral `LeaderTradeEvent`. A bounded real-data probe normalized 81 BTC
Up/Down 15-minute events across five markets without credentials or venue
mutation.

The local closure probe verified repeated polling, duplicate suppression,
restart-stable identity, pagination, and visibility of non-trade activity.
However, no new execution occurred for the temporary test leader during the
measured window, so true first-seen latency did not receive a sample. Stage 1 is
therefore closed as `NO_GO` for advancing to Stage 2, rather than assigning a
misleading latency value.

## Scope and safety

This stage added only:

- a venue-neutral executed-leader event model and conservative position-effect
  classifier;
- a read-only application source port with an opaque checkpoint;
- a Polymarket public Data API / Gamma API adapter;
- a bounded research artifact command;
- deterministic fixtures and focused tests.

It did not add or change:

- a strategy or `CopyDecision`;
- an `OrderIntent`;
- Risk, Execution, PaperBroker, or live execution;
- submit, cancel, wallet, signing, or authenticated-account behavior;
- SQLite schema or persistence;
- runtime configuration, dependencies, Docker, server deployment, or services.

All network operations in this stage used public unauthenticated HTTP `GET`.
The selected public wallet was process-scoped, represented as `leader-001`, and
cleared after each probe. Its raw value and raw transaction hashes are absent
from tracked files and generated artifacts.

## Official source verification

Verified on 2026-07-28 against current official documentation:

- Data API base URL:
  `https://data-api.polymarket.com`
- `GET /trades` accepts a User Profile Address, provides side, asset,
  condition ID, size, price, epoch timestamp, outcome metadata, and transaction
  hash. `takerOnly` defaults to `true`; the adapter explicitly sends `false`.
- `GET /activity` supports `type=TRADE`, time windows, and stable
  `sortDirection=ASC` pagination.
- `GET /positions` supports `sizeThreshold=0`.
- `GET /closed-positions` provides closed-position evidence.
- Data API documented limits are 200 requests / 10 seconds for `/trades` and
  150 requests / 10 seconds for positions endpoints.
- The authenticated User WebSocket is account-scoped order/trade delivery and
  was not treated as an arbitrary-leader source.

Official references:

- <https://docs.polymarket.com/api-reference/predictions/overview>
- <https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets>
- <https://docs.polymarket.com/api-reference/core/get-user-activity>
- <https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user>
- <https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user>
- <https://docs.polymarket.com/api-reference/rate-limits>
- <https://docs.polymarket.com/trading/realtime-order-updates>
- <https://docs.polymarket.com/getting-started/sdks-apis>

The installed official SDK exposes `list_trades`, `list_activity`,
`list_positions`, and `list_closed_positions`. Two initial bounded SDK network
probes did not complete within their command timeouts in this environment,
while direct calls to the same official REST endpoints succeeded. The Stage 1
adapter therefore uses a small standard-library REST transport with:

- fixed official base URLs;
- no authentication headers;
- a 10-second request timeout;
- at most two attempts for 429, server, timeout, or network read failures;
- a 5 MB response cap;
- at most five concurrent metadata reads.

No dependency was added or upgraded.

## Accepted and corrected research notes

Useful items retained from
`POLYSIA_COPYTRADING_STAGE1_RESEARCH_NOTES.md`:

- public Data API as the first source;
- `takerOnly=false`;
- `sizeThreshold=0`;
- strict wallet alias sanitization;
- composite stable event identity;
- conservative OPEN / INCREASE / REDUCE / CLOSE / UNKNOWN reconstruction;
- Gamma identifier-based BTC 15-minute market and outcome verification;
- bounded pagination, checksums, and fail-closed ambiguity.

Corrections or restrictions:

- the current official Activity documentation caps `offset` at 5,000, not
  10,000;
- the SDK does cover the relevant public endpoints, although its network path
  was not reliable in the initial local probes;
- no full raw wallet payload is retained; `raw-events.jsonl` is a sanitized
  source projection;
- no WebSocket or authenticated account path is used;
- non-BTC events are counted as correctly filtered, not mapping failures.

## Implemented contracts

### `LeaderTradeEvent`

The frozen domain event contains:

- stable SHA-256 event ID;
- source ID and safe leader alias;
- condition and outcome/token references;
- BUY or SELL;
- OPEN, INCREASE, REDUCE, CLOSE, or UNKNOWN;
- Decimal price and size;
- aware UTC execution and observation timestamps;
- hashed evidence reference;
- schema version.

It rejects raw wallet aliases, non-positive size, out-of-range prediction-market
prices, non-UTC timestamps, and observation times preceding execution.

### Event identity

The event ID hashes the source evidence fields:

```text
wallet + transaction hash + condition ID + asset + side + price + size + timestamp
```

The raw wallet and transaction hash contribute to identity but never appear in
the normalized event. Duplicate rows produce the same ID and are suppressed.

### BTC 15-minute mapping

Mapping requires all of:

1. exact `btc-updown-15m-<epoch>` event-slug pattern;
2. exactly one official Gamma event and market;
3. matching condition ID;
4. matching token ID and Up/Down outcome;
5. market end time equal to slug start plus 15 minutes.

Title text alone is never sufficient.

### Position-effect classification

Inventory is reconstructed per:

```text
leader alias + condition ID + outcome/token
```

- first BUY with a proven zero opening inventory: OPEN;
- later BUY with known inventory: INCREASE;
- SELL smaller than known inventory: REDUCE;
- SELL equal to known inventory: CLOSE;
- missing opening inventory or oversell: UNKNOWN.

If opening inventory is not proven, the first event and all dependent events
remain UNKNOWN. UNKNOWN is fail-closed and cannot create an intent.

## Real-data evidence

Final bounded probe:

| Metric | Result |
|---|---:|
| Window | 6 hours |
| Pages read | 2 |
| Raw events observed | 101 |
| Correctly filtered non-BTC 15m events | 20 |
| Target BTC 15m events | 81 |
| Valid normalized events | 81 |
| Mapping success | 100% |
| Missing/rejected target events | 0 |
| Duplicate events | 0 |
| BUY | 79 |
| SELL | 2 |
| OPEN / INCREASE / REDUCE / CLOSE | 0 |
| UNKNOWN | 81 |
| Position-effect classification | 0% |
| Source errors | 0 |
| Credentials used | No |
| Venue mutation | No |

The sample was deliberately selected from current public BTC 15-minute activity
and contained both BUY and SELL evidence. It is a feasibility sample, not an
owner-approved production leader.

The final sanitized source-behavior probe observed 100 all-side trades versus
12 taker-only trades on its bounded coverage page, confirming that
`takerOnly=false` can materially improve maker coverage. Both the all-side and
Activity pages reached their 100-row probe cap and are not population
estimates.

The 0% real classification rate is deliberate. The source window was complete
for the queried pages, but the probe did not prove the leader's opening
inventory for every market/outcome. Treating the first observed BUY as OPEN
would violate the Stage 1 rule that BUY is not automatically an entry. Fixture
tests separately prove the classifier's OPEN / INCREASE / REDUCE / CLOSE
behavior when a zero opening inventory is explicitly supplied.

## Latency interpretation

The final historical one-shot sample reported:

- p50 first-observation lag: 397 seconds;
- p95 first-observation lag: 12,994 seconds;
- maximum: 13,653 seconds.

These values are expected for a one-shot query over a six-hour historical
window. They are not Data API indexing latency and must not be used to approve
a 15-minute copy-entry policy. The task attempted an additional repeated live
page probe, but that auxiliary command timed out before producing evidence.
Metadata reads were then changed from sequential to bounded concurrency, and
the final 500-row probe completed successfully.

Continuous polling must separately measure:

```text
Data API executed timestamp -> first successful PolySia observation timestamp
```

with local NTP uncertainty recorded.

## Local Stage 1 closure probe

Run on 2026-07-28 on the owner's local system using only unauthenticated
official Gamma and Data API `GET` requests. The source wallet was discovered
from current public BTC 15-minute market activity and held only in process
memory. It was represented as `test-leader-001` with sanitized digest
`fb63284ab93b`; this is a technical test source, not an approved Copy Trading
leader.

The successful bounded run produced:

| Metric | Result |
|---|---:|
| Selection | Recent active BTC 15-minute public wallet |
| Polls | 6 attempted, 6 successful |
| Unique events observed | 5 |
| Repeated observations suppressed | 25 |
| New executions during measured window | 0 |
| First-seen latency samples | 0 |
| Independent frozen-window reads | 5 events, then 5 events |
| Restart count and digest | Stable |
| Pagination | 3 pages, complete |
| Source errors | 0 |
| Credentials or venue mutation | None |

The duplicate count measures repeated observation of already-known stable event
IDs across polls; it is not evidence that the Data API returned corrupt rows.
Two independently initialized reads of the same frozen window produced the same
count and digest. Re-reading that window in two-event pages reproduced the same
event-ID set.

Wallet-wide non-trade Activity reads over the preceding 24 hours returned 33
`REDEEM` rows and zero `SPLIT`, `MERGE`, or `CONVERSION` rows. This proves the
read surface can expose non-trade activity for the temporary source; it does
not by itself map those rows to BTC 15-minute position effects.

A second and final bounded selection window waited 45 seconds for a fresh
current-market execution. It observed none and did not find a fallback wallet
active within the preceding three minutes, so the probe stopped without
further retries. This is market-sample insufficiency, not an HTTP, credential,
or product error.

No p50, p95, or maximum live latency is reported because the sample count is
zero. Historical age and the lag of a previously executed trade are not valid
substitutes for first-seen indexing latency.

## Read-only 403 connectivity diagnostic

Run on 2026-07-28 after the owner changed the local VPN route. The comparison
used only official Data API and Gamma API public reads. It changed no VPN,
firewall, server, container, credential, account, or venue state.

### Results

| Location and client | Data trades | Data activity | Data positions | Gamma events |
|---|---:|---:|---:|---:|
| Local curl, empty User-Agent | 200 | 200 | 200 | 200 |
| Local curl, PolySia User-Agent | 200 | 200 | 200 | 200 |
| Finland server curl, empty User-Agent | 200 | 200 | 200 | 200 |
| Finland server curl, PolySia User-Agent | 200 | 200 | 200 | 200 |

Local curl requests completed in 0.718–1.244 seconds. Server requests completed
in 0.038–0.216 seconds. The User-Agent did not change status behavior in this
sample.

Additional client-path checks:

- local synchronous HTTPX returned 200 for Data and Gamma in 1.943 seconds;
- local asynchronous HTTPX did not finish within a 30-second process cap;
- the local official SDK, which uses an asynchronous HTTP path, did not produce
  a result within a 70-second process cap;
- inside the healthy Finland container, official SDK 0.2.0 returned one Data
  trade page in 0.295 seconds and one Gamma event page in 0.381 seconds.

One SSH connection attempt timed out during banner exchange. A later bounded
connection succeeded and all server API probes completed. This was an SSH-path
transient, not a Polymarket HTTP 403.

### Finding

No persistent Polymarket 403 exists on either currently tested route. Earlier
local 403 responses were intermittent and are consistent with a local
client/VPN/Cloudflare route interaction, not an invalid endpoint or permanent
geographic block. The exact former VPN exit route was not retained, so this is
an evidence-based inference rather than a proven root cause.

The remaining reproducible local issue is narrower: asynchronous HTTP stalls on
the current Windows/VPN path while synchronous REST works. The Stage 1 adapter
already uses bounded synchronous standard-library reads through
`asyncio.to_thread`, so the diagnostic does not require an architecture change.

Recommended future response:

1. run the four-request REST smoke check before a long local collection;
2. if REST returns 403, record only route label, UTC time, endpoint, client,
   User-Agent profile, and status, then compare against the Finland server;
3. prefer the server or the bounded REST adapter while local async HTTP stalls;
4. do not weaken geoblock or trading controls and do not rotate VPN routes
   during a measured run.

## Pagination and restart

The source:

- freezes `start` and `end` in an opaque checkpoint;
- advances a bounded offset;
- binds the checkpoint to the safe leader alias;
- uses deterministic event IDs for repeat and overlap suppression;
- rejects malformed or cross-leader checkpoints.

Fixture tests prove stable repeated identity, checkpoint continuation, disjoint
pages, and duplicate suppression. The real six-hour sample completed in two
pages without hitting the configured five-page cap. A separate real repeated
page probe timed out and therefore does not provide restart evidence.

## Artifacts

Generated, ignored artifacts:

```text
artifacts/copytrading/data-feasibility/
  raw-events.jsonl
  normalized-events.jsonl
  quality-report.json
  quality-report.md
  checksum.sha256
```

`raw-events.jsonl` is a sanitized source projection, not a retained full API
payload. All four payload checksums in `checksum.sha256` were independently
recomputed and matched.

Reproduction command:

```powershell
$env:POLYSIA_COPYTRADING_LEADER_ADDRESS = "<approved-profile-wallet>"
$env:PYTHONPATH = (Resolve-Path "src").Path
conda run --no-capture-output -n PolySia python scripts/copytrading-stage1.py `
  --window-minutes 360 --page-size 100 --max-pages 5
Remove-Item Env:POLYSIA_COPYTRADING_LEADER_ADDRESS
```

Do not place the raw address in Git, a command argument, a report, or a shared
shell transcript.

## Validation

Focused implementation validation:

```text
python -m ruff check <Stage 1 files>
python -m mypy <Stage 1 source files>
python -m pytest -q \
  tests/unit/domain/copytrading \
  tests/unit/adapters/test_polymarket_copytrading_source.py \
  tests/contract/test_polymarket_sdk_surface.py \
  tests/architecture/test_boundaries.py
```

Result: 18 focused tests passed; focused Ruff and Mypy passed.

The repository-wide validation is recorded in the final task delivery after the
final diff review.

## Decision

**`NO_GO` for Stage 2. Stage 1 is closed and no Stage 2 work was started.**

Proven:

- official public arbitrary-profile trade reads are available;
- required trade fields are present;
- strict BTC 15-minute market/outcome mapping is deterministic;
- maker activity can be omitted by the default taker-only behavior;
- stable sanitized event normalization is possible;
- OPEN / INCREASE / REDUCE / CLOSE can be reconstructed only when opening
  inventory is proven; otherwise UNKNOWN is enforced;
- no credentials or mutation path are required.

Blocking conditions:

1. a longer read-only run must capture enough new executions to measure true
   p50, p95, and maximum first-seen latency;
2. the owner must later approve one to three leader identities through
   protected, untracked configuration before any Copy Trading evaluation;
3. the owner must decide whether and for how long sanitized public evidence may
   be retained;
4. proxy-wallet / EOA identity grouping must be explicitly decided;
5. observed non-trade rows and opposite-outcome behavior must remain
   fail-closed until their position effects are proven.

Closed by the local probe:

- repeated polling and stable duplicate suppression;
- restart-stable frozen-window identity;
- real offset pagination for the frozen window;
- read-only visibility of at least one non-trade activity type.

## Rollback

Delete the Stage 1 source, port, domain, script, fixtures, tests, and this
handoff, then delete the experimental branch. Generated artifacts are ignored
and can be removed independently. No database, dependency, configuration,
server, account, or venue state requires restoration.

## Exact next task

Do not begin Stage 2. If the owner chooses to revisit the `NO_GO`, run one
longer, bounded, read-only collection against a deliberately active temporary
or owner-approved leader until enough new executions exist for a meaningful
latency distribution. Preserve the current duplicate, restart, pagination, and
non-trade evidence. Do not create a strategy, create an intent, or place/cancel
any order.
