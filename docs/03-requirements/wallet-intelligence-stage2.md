# Wallet Intelligence Stage 2 — Candidate Intelligence v1

- **Status:** APPROVED FOR IMPLEMENTATION; deployment remains a separate owner action
- **Scope:** canonical identity, historical features, readiness, policy evaluation,
  deterministic ranking, and a stable candidate-pool query
- **External mutation:** none; the only permitted network operation is the existing
  owner-approved read-only PolyCop ingestion
- **Out of scope:** Polymarket enrichment, Backtest, signals, Paper/Shadow/Live Trading,
  order creation, deployment, timer enablement, and external alert delivery

## Goal

Turn each healthy Stage 1 source snapshot into a reproducible, auditable candidate
pool without inventing unavailable evidence. PolyCop remains a discovery source.
Official Polymarket activity and trade history remain a future enrichment input and
will be required before performance claims or trading decisions.

## Current and target boundary

```text
CURRENT after this change
Stage 1 source snapshots
  -> Stage 2A canonical wallet identity and source links
  -> Stage 2B snapshot-derived features and data readiness
  -> Stage 2C versioned policy evaluation and deterministic ranking
  -> candidate_trading_pool_current (read-only query contract)

DEFERRED
Official Polymarket history -> trading-quality features -> Backtest -> controlled runtime
```

The protected wallet-intelligence SQLite database remains separate from the main
trading database. Stage 2 uses additive tables and a separate schema-version record;
Stage 1 code can ignore those tables during rollback.

## Canonical identity

- A canonical wallet is `(chain, normalized_address)`, not a person.
- Current PolyCop rows map explicitly to `chain=polygon`.
- EVM addresses are normalized to lowercase after strict `0x` plus 40-hex validation.
- `wallet_id` is the deterministic SHA-256 of `chain + NUL + normalized_address`.
- `candidate_wallet_identities` remains the protected Stage 1 source identity.
- `wallet_source_links` maps each source identity to one canonical wallet and preserves
  provenance. One canonical wallet may have links from multiple future sources.
- Full addresses may exist only in protected identity tables. Ordinary views, health,
  CLI output, tests, reports, commits, CI output, and PR text use `wallet_id` or a mask.

## Time and feature model

Every feature records its source snapshot and the following distinct times:

- `effective_at`: the Stage 1 snapshot capture time;
- `observed_at`: when the source response was observed (currently the same capture time);
- `ingested_at`: when Stage 1 accepted the complete snapshot;
- `calculated_at`: when Stage 2 calculated the feature set.

Historical lookups are point-in-time safe: a 1-, 7-, or 30-day comparison uses the
latest accepted observation at or before `effective_at - window`. Future observations
are never visible. A positive rank delta means improvement:
`historical_rank - current_rank`. A positive score delta means
`current_score - historical_score`.

Candidate Intelligence v1 calculates, when evidence exists:

- source rank and source score;
- first seen, last seen, observation count, distinct observed days;
- eligible source-snapshot count and presence ratio;
- snapshot age and staleness;
- previous, 1-day, 7-day, and 30-day rank/score deltas;
- best/worst rank and population volatility/stability for rank and score.

Presence ratio is `wallet observations / accepted source snapshots` from the wallet's
first observation through the current snapshot. Stability is `1 / (1 + population
standard deviation)` and is `NULL` until at least two observations exist. Windowed
features remain `NULL` until qualifying historical evidence exists; cold start never
fabricates zeroes.

## Readiness and candidate policy

Readiness and selection are independent dimensions:

- `READY`: identity, current snapshot, freshness, rank, and source score are valid;
- `PARTIAL`: valid current identity/rank but a required ranking input is unavailable;
- `STALE`: valid evidence exceeds the configured freshness threshold;
- `INVALID`: identity or required current evidence is malformed;
- `UNKNOWN`: readiness cannot be established.

Candidate Policy v1 is deliberately non-predictive:

- `READY` -> `SELECTED`;
- `PARTIAL`, `STALE`, or `UNKNOWN` -> `WATCHLIST`;
- `INVALID` -> `INELIGIBLE`.

This policy acknowledges that PolyCop already limits the reviewed endpoint to score
50 or higher. It does not claim profitability. All `SELECTED` wallets are ranked by
source score descending, source rank ascending, presence ratio descending, and
`wallet_id` ascending as the final deterministic tie-break. Only selected wallets
receive a contiguous candidate rank.

The stable `candidate_trading_pool_current` view exposes all current evaluations and
their status without addresses. Consumers request Top N with
`candidate_status='SELECTED' ORDER BY candidate_rank`. Historical feature and policy
rows remain immutable, while this current view recalculates effective data age on
every read. Once the recorded `stale_after_seconds` threshold expires, a previously
selected row is exposed as `STALE` / `WATCHLIST`, its candidate rank is cleared, and
selected-only reads exclude it.

## Versioning and idempotency

The processing identity is:

```text
source_snapshot_id
+ feature_set_version
+ candidate_policy_id
+ candidate_policy_version
+ ranking_version
```

A database constraint permits at most one successful run for an identity. Replays
reuse that run. Wallet features and policy outcomes are immutable run history; the
current pointer is published only after the complete result validates. Effective
freshness is intentionally not part of the immutable processing identity.

Stage 2 never materializes all retained observations in one collection. It loads the
current snapshot as a bounded worklist, rejects more than 25,000 current wallets,
and reads retained wallet history in batches of 32 (with a storage-side maximum of
64 keys per request). This keeps memory use bounded by current output plus one
history batch rather than by total 365-day retention volume.

## Cross-process serialization

Startup, scheduled, and manual entry points share one SQLite lease:

- acquisition occurs atomically under `BEGIN IMMEDIATE`;
- the row records owner, acquisition/heartbeat/expiry times, and a monotonic fencing
  token;
- an unexpired lease cannot be stolen;
- an expired lease can be recovered after a crash;
- renewal and release require the owner and fencing token;
- atomic publication verifies the same live lease inside its transaction, preventing
  an expired previous owner from publishing after takeover.

No SQLite transaction is held across a network request or the full calculation.

## Startup, freshness, and last-known-good behavior

```text
Acquire lease
  -> initialize additive schema
  -> inspect latest healthy Stage 1 snapshot
  -> reuse when sufficiently fresh; otherwise run Stage 1 sync
  -> renew lease
  -> reuse matching successful Stage 2 run or calculate it
  -> validate complete counts and deterministic ranks
  -> atomically publish current pool
  -> release lease
```

Any Stage 1, Stage 2, lease, validation, or publication failure leaves the previous
current candidate pool unchanged. Safe health state becomes warning, stale, or failed;
partial results are never current.

## Retention and recovery

- Stage 1 normalized snapshot history remains 365 days by default.
- Stage 1 quarantine evidence remains 30 days by default.
- Stage 2 structured run, feature, and policy history remains at least 365 days by
  default; the current run is never pruned.
- No healthy raw-JSON retention is claimed or introduced.
- Existing online backup and disposable restore rehearsal cover the additive tables.
- Rollback uses the earlier application revision, which ignores Stage 2 tables; the
  protected database is retained for forward recovery.

## Definition of done before deployment

- additive migration from an existing Stage 1 database preserves all Stage 1 data;
- identity, multi-source linking, time-safe features, cold start, NULL behavior,
  versioning, deterministic ties, idempotency, retention, atomic publication, and
  last-known-good behavior have automated coverage;
- concurrent connections/process-equivalent calls, lease expiry, renewal, stale-owner
  fencing, and recovery have automated coverage;
- CLI provides full pipeline, safe health, and deterministic Top-N reads;
- Compose/systemd definitions invoke the same full pipeline but are not installed or
  enabled by this change;
- a real approved read-only smoke produces masked Before/After evidence and Top 10 /
  Top 100 deterministic checks;
- repository quality gates and a security review pass;
- the change is committed, reviewed through PR/CI, and merged normally;
- deployment and every trading action remain unperformed.
