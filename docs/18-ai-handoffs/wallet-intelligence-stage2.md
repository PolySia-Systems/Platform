# Wallet Intelligence Stage 2 Handoff

## Document control

| Field | Value |
|---|---|
| Task | Stage 2 Candidate Intelligence v1 |
| Date | 2026-08-23 |
| Starting commit | `b64057ca737e071d7ae1b9921b7c85ce8dcd39b2` |
| Implementation commit | `eac6feee625127e0e17919436571b4d15066fee9` |
| Working branch | `codex/wallet-intelligence-stage2` |
| External mutation | None; owner-approved public GET reads only |
| Deployment | Not performed |

## Outcome

PolySia now has a complete data-only path from a healthy Stage 1 source snapshot
to an address-free current candidate pool. It canonicalizes wallet identity,
calculates point-in-time-safe source-derived features, separates data readiness
from versioned policy evaluation, ranks deterministically, and atomically
publishes only a complete result. Startup, scheduled, and manual paths share one
persistent SQLite lease with fencing and preserve the last known good pool on
every failure.

This change does not enrich wallets from official Polymarket trade history,
claim profitability, generate signals, backtest, Paper/Shadow trade, place or
cancel orders, deploy services, or enable Live behavior.

## Current architecture

```text
PolyCop Stage 1 snapshot
  -> canonical wallet identity (chain + normalized address)
  -> source link and provenance
  -> source-derived time-safe features
  -> independent readiness evaluation
  -> Candidate Policy v1
  -> deterministic ranking
  -> atomic address-free current pool
```

- Canonical wallet identity is deterministic across sources. One canonical
  wallet may retain multiple source links; it is not treated as a person.
- Full addresses remain confined to the protected `canonical_wallets` and Stage
  1 identity tables. Normal pool and health output use only internal wallet IDs.
- Historical feature and policy rows are immutable and carry effective,
  observed, ingested, calculated, source, method, and version context.
- Cold-start historical windows remain `NULL`; absence of history is never
  rewritten as zero.
- Candidate Policy v1 selects `READY`, watchlists `PARTIAL` / `STALE` /
  `UNKNOWN`, and marks `INVALID` ineligible. It is a discovery policy only.
- Current-pool reads apply the stored stale threshold at read time. Expired
  historical selections become `STALE` / `WATCHLIST`, lose rank, and are
  excluded from selected-only reads without changing immutable history.
- The processing identity is source snapshot + feature-set version + policy ID
  and version + ranking version. A partial unique index permits one successful
  run per identity.
- Publication verifies the live owner and fencing token in the same SQLite
  transaction that writes canonical identities, features, evaluations, run
  counts, and the current pointer.
- Lease release retains its row so fencing tokens remain monotonic across normal
  release, expiry recovery, and process takeover.
- Memory is bounded: the current worklist is capped at 25,000 wallets and
  retained histories are loaded in batches of 32 through a storage boundary
  capped at 64 keys. Stage 2 does not materialize all retained observations.

## Main paths

- Specification: `docs/03-requirements/wallet-intelligence-stage2.md`
- Domain: `src/polysia/domain/wallet_intelligence/candidate_intelligence.py`
- Port: `src/polysia/application/ports/candidate_intelligence.py`
- Services: `src/polysia/application/services/candidate_intelligence.py`
- SQLite owner/schema: `src/polysia/storage/candidate_intelligence.py` and
  `src/polysia/storage/candidate_intelligence_schema.sql`
- CLI: `src/polysia/cli_commands/wallet_intelligence.py`
- Operations: `docs/10-operations/wallet-intelligence-ingestion.md`
- Tests: `tests/unit/application/test_candidate_intelligence.py` and
  `tests/unit/storage/test_candidate_intelligence_storage.py`

## Security review and remediation

Durable review `cbd74c6d-5a37-4675-bf54-09096ac49cb5` inspected all 13 changed
source/config surfaces in its pre-remediation snapshot. It reported two issues:

1. cumulative retained-history materialization could exhaust the 512 MiB
   service;
2. an idempotent replay could expose an expired historical selection as current.

Both were fixed at their shared boundaries and received regression tests. The
original triggers no longer reproduce: an oversized current snapshot fails
before retained-history loading, history reads are key-batched, and an expired
row is absent from selected-only reads while its immutable historical
evaluation remains unchanged. The review found no wallet-address disclosure,
SQL injection, stale-owner publication, lease bypass, or external mutation path.

## Validation

The final implementation passed:

- `python scripts/validate_standards.py --mode full`;
- `python -m compileall -q src tests`;
- `python -m ruff check .`;
- `python -m mypy src` — 158 source files;
- `python -m pytest -q` — 747 passed;
- `python -m pip check`;
- `python -m polysia.security.secret_scan`;
- `python -m build` — source distribution and wheel built;
- `python -m pre_commit run --all-files`;
- Compose rendering with the tracked example environment;
- wheel inspection confirming both wallet-intelligence SQL schemas are packaged;
- strict OSV audit of the official lock in an isolated environment — no known
  vulnerabilities;
- isolated CycloneDX SBOM generation and `pip check`;
- `git diff --check` and final content review.

The whole-workstation audit separately reports an unrelated orphan
`cryptography==48.0.0` installation with no `Required-by` packages. It is absent
from PolySia declarations and lock files and was not modified. The isolated
locked audit is the project and CI evidence.

## Real read-only smoke

The final owner-authorized smoke:

- fetched 22 dynamic PolyCop pages and 2,109 unique wallets;
- published 2,109 canonical features and evaluations, all `READY` / `SELECTED`;
- repeated with no second source fetch and no second Stage 2 run;
- returned deterministic address-free Top 10 output;
- created and verified a backup with SHA-256
  `36c213beee151938d8c4a0a1e64396c3bfa7b44951868713278db8ec538265ab`;
- restored and reconciled one Stage 1 snapshot, 2,109 Stage 1 rows, one Stage 2
  run, and 2,109 current pool rows.

The disposable database, backups, reports, and full wallet addresses were
removed after verification.

## Remaining work and next safe step

- PolyCop remains a discovery source with an undocumented external API and a
  score-50-or-higher leaderboard, not the full Polymarket wallet universe.
- Official Polymarket activity/trade enrichment and verified trading metrics are
  deliberately deferred.
- External alert delivery and encrypted off-host backup remain operational
  limitations inherited from Stage 1.
- Deployment and timer enablement were not performed.

The next safe step is a separately reviewed data-only deployment of Stage 1 and
Stage 2, followed by startup/daily/idempotency/failure observation. Only after
that evidence should an address-free candidate consumer enter Shadow/Paper
strategy research. Live trading still requires separate evidence and explicit
authorization.
