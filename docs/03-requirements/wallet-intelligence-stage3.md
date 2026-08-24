# Wallet Intelligence Stage 3 — Copyability Selection v0.1

- **Status:** APPROVED FOR IMPLEMENTATION; deployment remains a separate owner action
- **Scope:** deterministic, versioned, auditable selection-only pools derived from
  Stage 2 Candidate Intelligence
- **External mutation:** none; the only permitted network operation remains the
  existing owner-approved read-only PolyCop ingestion
- **Out of scope:** Polymarket enrichment, copyability backtest, signals, Paper /
  Shadow / Live Trading, order creation, candidate-file generation, deployment,
  timer enablement, machine learning, and external alert delivery

## Goal

Turn each healthy Stage 2 run into reproducible selection pools without inventing
unavailable evidence. Stage 3 ranks wallets for later Shadow research. It does
not prove profitability, authorize trading, or promote any wallet to Live review.

PolyCop remains an undocumented discovery/proxy source. Official Polymarket
activity, a realistic copyability backtest, independent Shadow evidence, human
review, and explicit owner authorization remain required before Tiny-Live.

## Current and target boundary

```text
CURRENT after this change
Stage 1 source snapshots
  -> Stage 2 canonical identity, features, readiness, and candidate policy
  -> Stage 3 copyability scoring and independent pool membership
  -> copyability_pools_current (read-only query contract)

DEFERRED
Official Polymarket history -> trading-quality features -> copyability backtest
  -> Shadow evidence -> review -> Tiny-Live (separate authorization)
```

The protected wallet-intelligence SQLite database remains separate from the main
trading database. Stage 3 uses additive tables and a separate schema-version
record. Stage 1 and Stage 2 code can ignore those tables during rollback.

## Pools and status

Stage 3 publishes independent memberships, not a permanent wallet identity:

- `SHADOW_ALPHA`: copyability-oriented Top 50 by default among eligible wallets;
- `SHADOW_STRESS`: high-activity Top 100 by default among eligible wallets;
- `LIVE_REVIEW_CANDIDATE`: implemented and forced empty in v0.1;
- `REJECTED`: only invalid readiness or unparseable / out-of-range metrics.

Alpha and Stress are separate policies and may overlap. A valid wallet that is
not a member of Alpha or Stress is `WATCHLIST`, not rejected. High PolyCop hedge
proxies exclude Alpha and do not reject.

Eligibility:

- Alpha requires `READY` readiness, at least one source copyability metric, a
  present copyability score, a present alpha score, and no hedge block
  (`hedged_pct >= 50`, hedge-risk percentile `>= 80`, or a positive `hedged`
  flag without `hedged_pct`);
- Stress requires a present activity score and readiness that is not `STALE`,
  `UNKNOWN`, or `INVALID`.

Missing 7-day / 30-day history remains `NULL`, is never rewritten as zero, and
does not block Alpha or Stress.

## Scoring

Feature-set `copyability-v0.1`, policy `copyability-selection` `v0.1`, and
ranking `percentile-alpha-stress-v0.1` calculate 0–100 percentile components
with Decimal arithmetic:

| Component | Default alpha weight | Inputs |
|---|---|---|
| copyability | 35% | copy-backtest PnL, recent-20 PnL/win-rate, inverted copy-loss rate and slippage, presence ratio |
| performance | 25% | actual PnL, ROI, win rate, average monthly PnL, average profit/loss ratio |
| recent edge | 15% | last-2d, recent-20 PnL/win-rate, inverted slippage, 7-day rank/score deltas |
| activity | 10% | volume, markets traded, trading days, observation count |
| confidence | 10% | observation count, presence ratio, metric completeness |
| stability | 5% | rank stability, score stability |

Missing values stay `NULL` and are omitted from that wallet's component mean.
Presence ratio alone cannot create a copyability score; at least one of the five
source copyability metrics must be present. PolyCop percentage metrics
`copy_loss_rate`, `r20_slip`, `r20_wr`, `win_rate`, and `hedged_pct` must be in
`0`–`100`, while `buy_price` must be in `0`–`1`.
Ties use average rank. A one-value population scores 50. Negative values remain
in the percentile scale for signed metrics such as PnL and ROI; they are not
clipped to zero. Bounded rates and prices outside their documented source units
are rejected. `copy_loss_rate` and `r20_slip` are inverted after percentile
conversion. Alpha score is a renormalized weighted mean of available components.

`hedged` is a non-negative integer proxy, not a verified Polymarket hedge
ratio. Treat `0` as unhedged and `>0` as a hedge flag. `hedged_pct` must be in
`0`–`100` when present.

## Versioning, lease, and publication

The processing identity is:

```text
stage2_run_id
+ feature_set_version
+ policy_id
+ policy_version
+ ranking_version
```

A partial unique index permits one successful run per identity. Replays reuse
that run. Scores and memberships are immutable run history. Publication writes
scores, memberships, run counts, and the current pointer in one SQLite
transaction after verifying the live pipeline owner and fencing token.

A Stage 3 failure records a failed run, leaves the previous Stage 3 current
pointer unchanged, and does not rewrite healthy Stage 1 or Stage 2 state. The
shared pipeline lease is renewed before Stage 3 and is never held across a
network read or the full calculation.

Retention matches Stage 2: at least 365 days of structured history; the current
pointer is never pruned. Existing backup and restore rehearsal cover the
additive tables.

## CLI contract

`wallet-intelligence ensure` runs Stage 1 -> Stage 2 -> Stage 3 under one
lease. `wallet-intelligence selection --pool` reads:

- `SHADOW_ALPHA`
- `SHADOW_STRESS`
- `LIVE_REVIEW_CANDIDATE`
- `REJECTED`
- `WATCHLIST`

Ordinary output contains `wallet_id` only. Full addresses remain confined to
protected identity tables.

Health adds `copyability_selection` only when a Stage 2 current pool exists.
Missing Stage 3 after a healthy Stage 2 is warning, not a reason to invent
Stage 2 failure. `LIVE_REVIEW_CANDIDATE` must remain empty.

## Definition of done before deployment

- additive migration from an existing Stage 1/2 database preserves prior rows;
- Decimal percentiles, NULL history, independent pools, empty Live review,
  rejection vs watchlist, idempotent replay, lease fencing, atomic publication,
  last-known-good preservation, retention, backup/restore counts, and address
  non-disclosure have automated coverage;
- a disposable owner-approved read-only smoke records sanitized counts and then
  deletes raw addresses;
- repository quality gates pass;
- the change is committed and opened as a draft PR;
- deployment, timer enablement, and every trading action remain unperformed.
