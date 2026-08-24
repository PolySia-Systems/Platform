# Wallet Intelligence Stage 3 Handoff

## Document control

| Field | Value |
|---|---|
| Task | Stage 3 Copyability Selection v0.1 |
| Date | 2026-08-24 |
| Starting commit | `adffb98` |
| Working branch | `codex/wallet-intelligence-stage3` |
| External mutation | None; owner-approved public GET reads only |
| Deployment | Not performed |

## Outcome

PolySia now has a complete data-only path from a healthy Stage 1 snapshot through
Stage 2 Candidate Intelligence to independent copyability selection pools:

- `SHADOW_ALPHA`
- `SHADOW_STRESS`
- `LIVE_REVIEW_CANDIDATE` (always empty in v0.1)
- `REJECTED`

Valid non-members remain `WATCHLIST`. Alpha and Stress are independent and may
overlap. Publication is atomic, versioned, and fenced by the existing pipeline
lease. Ordinary CLI, health, and pool output use `wallet_id` only.

This change does not enrich wallets from official Polymarket trade history,
claim profitability, generate signals, backtest, Paper/Shadow trade, place or
cancel orders, emit candidate files, deploy services, or enable Live behavior.

## Current architecture

```text
PolyCop Stage 1 snapshot
  -> Stage 2 canonical identity, features, readiness, and candidate policy
  -> Stage 3 percentile copyability scores
  -> independent Alpha / Stress / Rejected memberships
  -> atomic address-free current pools
```

- Scoring uses Decimal percentiles. Missing values stay `NULL` and are omitted
  from that wallet's component mean. Historical 7d/30d windows never block
  first-snapshot Alpha or Stress and are never rewritten as zero.
- Copy-loss rate and recent slippage are inverted after percentile conversion.
- High PolyCop hedge proxies exclude Alpha and do not reject.
- `LIVE_REVIEW_CANDIDATE` has a schema and CLI contract but no members until
  independent evidence exists.
- The processing identity is Stage 2 run + feature-set version + policy id and
  version + ranking version. One successful run is stored per identity.
- Publication verifies the live owner and fencing token in the same SQLite
  transaction that writes scores, memberships, counts, and the current pointer.
- A Stage 3 failure keeps the previous Stage 3 pointer and does not rewrite
  Stage 1 or Stage 2.

## Main paths

- Specification: `docs/03-requirements/wallet-intelligence-stage3.md`
- Domain: `src/polysia/domain/wallet_intelligence/copyability_selection.py`
- Port: `src/polysia/application/ports/copyability_selection.py`
- Service: `src/polysia/application/services/copyability_selection.py`
- SQLite owner/schema: `src/polysia/storage/copyability_selection.py` and
  `src/polysia/storage/copyability_selection_schema.sql`
- Pipeline wiring: `src/polysia/application/services/candidate_intelligence.py`
- CLI: `src/polysia/cli_commands/wallet_intelligence.py`
- Operations: `docs/10-operations/wallet-intelligence-ingestion.md`
- Tests: `tests/unit/domain/test_copyability_selection.py`,
  `tests/unit/application/test_copyability_selection_service.py`, and
  `tests/unit/storage/test_copyability_selection_storage.py`

## Read-only smoke

A disposable owner-approved PolyCop GET smoke, then deleted, observed:

- 21 dynamic pages and 2022 unique wallets;
- Stage 2 selected 2022;
- Stage 3 published Alpha 50, Stress 100, watchlist 1873, rejected 0, Live review 0;
- replay fetched no second source snapshot and reused Stage 2 and Stage 3 runs;
- Top 10 Alpha used 64-character `wallet_id` values only;
- backup restore rehearsal reported one Stage 3 run and 150 memberships.

Raw addresses and the disposable database were removed after verification.

## Remaining work and next safe step

- PolyCop remains a discovery source with an undocumented API and a score-50
  floor, not the full Polymarket wallet universe.
- Official Polymarket activity, verified trading metrics, copyability backtest,
  and Shadow evidence are deliberately deferred.
- Deployment and timer enablement were not performed.

The next safe step is a separately reviewed data-only deployment of Stages 1–3,
followed by startup/daily/idempotency/failure observation. Tiny-Live still
requires Polymarket verification, copyability backtest, Shadow evidence, human
review, and explicit owner authorization.
