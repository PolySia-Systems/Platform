# Wallet Intelligence Stage 4 — Dynamic Copyability Shadow v0.1

- **Status:** IMPLEMENTED ON REVIEW BRANCH; deployment remains a separate owner action
- **Scope:** read-only official Polymarket trade evidence, modeled historical
  copyability, and current-book Forward Shadow for current Stage 3 pools
- **External mutation:** public GET reads and protected local SQLite writes only
- **Out of scope:** signals, order intents, Paper orders, Live orders,
  cancellation, fund movement, profitability claims, and Live authorization

## Goal and boundary

Stage 4 replaces the fixed 102-wallet input for the new research path with the
deduplicated union of the current `SHADOW_ALPHA` and `SHADOW_STRESS` pools. It
observes verified trades across Polymarket event markets and measures what a
bounded follower simulation could have done after explicit costs.

The old Tiny-Live experiment is retained unchanged. Its source adapter defaults
to the reviewed BTC 15-minute scope. Only Stage 4 explicitly requests
`ALL_VERIFIED`, so this change cannot silently broaden the legacy Live path.

```text
Stage 3 current Alpha + Stress memberships
  -> canonical wallet_id union (overlap removed)
  -> protected address lookup inside SQLite
  -> official Polymarket /trades GET
  -> Gamma event/condition/outcome verification
  -> HISTORICAL cost model or FORWARD current order book
  -> immutable per-event and per-wallet evidence
  -> atomic current Shadow pointer + sanitized health
```

No Stage 4 application or domain contract imports an execution, risk, order, or
wallet-mutation port. The Compose service forces `TRADING_MODE=DATA_ONLY` and
`LIVE_TRADING_ENABLED=false`.

## Candidate and market contract

- Read only the current successful Stage 3 selection for the requested source.
- Include Alpha and Stress; deduplicate by canonical `wallet_id`.
- Resolve addresses only inside the protected repository and pass them to the
  official data adapter in memory. Stage 4 tables, views, CLI, health, and logs
  contain no address.
- Fetch `/trades` with `takerOnly=false`, bounded pages, concurrency, response
  size, retry, timeout, and the existing shared rate scheduler/circuit breaker.
- If one trade window reaches the official offset budget, split that UTC window
  recursively, deduplicate boundary events, and enforce a bounded total-page
  budget instead of publishing a truncated wallet history.
- Accept a trade only when Gamma returns one exact event slug and matching
  condition, token, outcome, and valid UTC market interval. Malformed or
  ambiguous evidence fails closed.
- An unavailable or empty executable current book is `UNKNOWN`, not a fill.

This covers verified event markets; it does not claim every market is liquid or
copyable. Liquidity is evaluated separately for each simulated event.

The external contract was checked against the official Polymarket
[`/trades`](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets),
[rate-limit](https://docs.polymarket.com/api-reference/rate-limits), and
[order-book](https://docs.polymarket.com/api-reference/market-data/get-order-book)
documentation on 2026-08-24. PolySia's 80 `/trades` requests per ten seconds is
stricter than the documented external limit.

## Evaluation modes

### HISTORICAL

Historical mode uses official wallet executions but does not claim access to a
historical order-book replay. It applies versioned assumptions for fee,
slippage, delay, maximum follower notional, and modeled liquidity. It is a
conservative cost-model backtest used for screening, not proof of a fill or
profit.

### FORWARD

Forward mode reads the current official order book after a newly observed
wallet trade. It walks executable depth on asks for buys and bids for sells,
caps follower notional, records observed liquidity and weighted price, and
charges the configured fee. Missing, stale, or insufficient book evidence is
`UNKNOWN`. A sell without a position established inside the same Shadow window
is also `UNKNOWN`; Stage 4 never invents an opening inventory.

The reviewed operational default polls every ten minutes with a 15-minute
window and a 15-minute maximum measured delay. The delay is deliberately
recorded as part of the evidence. This is Forward Shadow observation, not a
low-latency trading promise.

## Versioning, idempotency, and publication

The successful-run identity is:

```text
selection_run_id
+ mode
+ policy_version
+ cost_model_version and SHA-256 cost-input fingerprint
+ exact window_start and window_end
```

The cost fingerprint covers fee, historical slippage, historical delay,
maximum forward delay, follower notional, and modeled liquidity. Changing any
input therefore creates distinct evidence instead of replaying an incompatible
result.

Each run stores candidate memberships, event evaluations, and one wallet
summary. Publication validates completeness and uniqueness, then writes the
result and current pointer atomically. A failure records a safe code and keeps
the previous current run. Exact replays reuse the successful run.

The shared fenced SQLite lease prevents Stage 1–3 and Stage 4 from running at
the same time. The normal Stage 4 history retention is 365 days; current
Historical and Forward pointers are never pruned. Backup/restore validation
includes the Stage 4 schema, successful-run count, and evaluation count.

## Health and acceptance criteria

Health reports Stage 4 mode, versions, candidate/event/simulated/unknown counts,
and current run identifiers. It warns when evidence is missing, older than 36
hours, behind the current Stage 3 selection, empty, or followed by a failed
refresh. It never emits raw wallet addresses.

Definition of done before deployment:

- the legacy execution source remains BTC-15m by default;
- Stage 4 explicitly accepts verified non-BTC markets;
- dynamic Alpha/Stress overlap is processed once per wallet;
- fee, slippage, delay, liquidity, notional limits, PnL, and unknown reasons are
  deterministic and Decimal-safe;
- exact replay, shared lock, atomic publication, last-known-good preservation,
  address non-disclosure, retention, health, and real backup/restore rehearsal
  have automated coverage;
- repository quality and supply-chain gates pass;
- the branch is committed and a draft PR is ready;
- deployment and all order mutation remain unperformed.
