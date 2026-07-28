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
| Decision | `CONDITIONAL_GO` |

## Outcome

The official public Polymarket Data API can expose executed trades for a public
User Profile / Proxy Wallet with the fields needed to construct a
venue-neutral `LeaderTradeEvent`. A bounded real-data probe normalized 81 BTC
Up/Down 15-minute events across five markets without credentials or venue
mutation.

The result is a conditional data-shape and mapping success, not approval for a
strategy, persistence migration, paper execution, live execution, or production
operation. Continuous first-seen polling latency, approved-leader identity
management, complete non-truncated history, and non-trade position events still
need closure before Stage 2.

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

**`CONDITIONAL_GO` for source feasibility; do not start Stage 2 yet.**

Proven:

- official public arbitrary-profile trade reads are available;
- required trade fields are present;
- strict BTC 15-minute market/outcome mapping is deterministic;
- maker activity can be omitted by the default taker-only behavior;
- stable sanitized event normalization is possible;
- OPEN / INCREASE / REDUCE / CLOSE can be reconstructed only when opening
  inventory is proven; otherwise UNKNOWN is enforced;
- no credentials or mutation path are required.

Conditions not yet closed:

1. owner supplies one to three approved leader identifiers through protected,
   untracked configuration;
2. owner decides whether and for how long sanitized public evidence may be
   retained;
3. continuous polling measures true p50, p95, and maximum first-seen latency;
4. real repeated ingestion proves ordering and checkpoint recovery for the
   same frozen window;
5. proxy-wallet / EOA identity grouping is explicitly decided;
6. SPLIT, MERGE, REDEEM, conversion, and opposite-outcome behavior are measured
   or deliberately classified UNKNOWN.

## Rollback

Delete the Stage 1 source, port, domain, script, fixtures, tests, and this
handoff, then delete the experimental branch. Generated artifacts are ignored
and can be removed independently. No database, dependency, configuration,
server, account, or venue state requires restoration.

## Exact next task

Continue on `codex/copytrading-experiment` and perform only a Stage 1 closure
probe for one to three owner-approved leader aliases. Use protected, untracked
addresses; run bounded continuous polling long enough to measure true
first-seen latency; repeat a frozen non-truncated window to prove checkpoint
recovery; and measure non-trade position events. Update this handoff with a
final GO or NO_GO. Do not begin Stage 2, create a strategy, create an intent, or
place/cancel any order.
