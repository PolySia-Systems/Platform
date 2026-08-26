# Stage 4B v4 reliability, observability, and Shadow worker

## Status

PR `#92` merged as `c49652565cd7ddab6432e3488ca73fa1c9c352b5` and is deployed on
`Hetzner-Finland-Helsinki-01` in DATA_ONLY/Shadow. Schema v4 migrated forward.
The persistent worker is running. No real order was sent. `3x-ui` was not
restarted.

This change does not enable Live trading.

## Objective

Improve Stage 4B DATA_ONLY/Shadow reliability, observability, latency, and
economic validity without mixing Alpha and Stress results, without silently
replacing the v0.2 baseline policy, and without touching `3x-ui`.

## Behavior changed

- Schema v4 is additive. Mixed `FOLLOWER` remains the labeled baseline.
  `FOLLOWER_ALPHA` and `FOLLOWER_STRESS` start empty and are not backfilled.
- CLOSE and SETTLEMENT ledger rows persist Wallet and Pool attribution going
  forward. Historical CLOSE rows are backfilled from matching evaluations when
  `event_id` exists. Historical SETTLEMENT rows without `event_id` stay
  unattributed.
- Runtime price-drift protection defaults to off (`None`). Report-time
  walk-forward filters score recorded SIMULATED fills without look-ahead and
  are not a profitability claim.
- Health reports rolling 1h/6h/24h unknown separately from cumulative
  initialization backlog. Marks expose source timestamp, age, and freshness.
- Results include an operator summary, follower/Alpha/Stress views, P&L
  decomposition, Wallet/market attribution, mean/median/P95 in-process poll
  latency, and decision-readiness that refuses Live promotion.
- A persistent fenced `--loop` worker replaces the one-shot container poll.
  The previous one-minute timer remains as an optional schema-v3 fallback and
  must stay disabled while the v4 service is running.
- Terminal order-book 404 and closed-market tokens are skipped through a
  bounded negative cache.
- Encrypted off-host backup still has no approved destination. Local checksummed
  SQLite backup and disposable restore remain the recovery path.

## Schema migration and rollback

- Forward: v2 → v3 → v4 is transactional and idempotent. v4 code migrates a v3
  database forward, including dropping and recreating
  `continuous_shadow_portfolio_current` around the portfolios rebuild.
- Rollback: stop the persistent worker, restore the verified pre-migration
  backup, start the prior schema-v3 image, and re-enable the oneshot timer.
  v3 code against a v4 database fails closed.
- Stage 4A schema v1 is unchanged.

## Local validation

Exact commands and results from this workstation:

- `python scripts/validate_standards.py --mode full` — PASS, blocking=0
- `python -m compileall -q src tests` — PASS
- `python -m ruff check .` — PASS
- `python -m mypy src` — PASS, 172 source files
- `python -m pytest -q` — PASS, 820 tests
- `python -m pip check` — PASS
- `python -m polysia.security.secret_scan` — PASS
- `python -m build` — PASS, `polysia-0.1.0` sdist and wheel
- `git diff --check` — PASS
- `python -m pip_audit --strict --vulnerability-service osv` — FAIL on
  workstation `cryptography 48.0.0` advisories PYSEC-2026-3552/3553/3554 and
  GHSA-537c-gmf6-5ccf. This change does not modify lockfiles or cryptography.
  CI supply-chain runs only when dependency files change.

## Safety

- Compose and systemd keep `TRADING_MODE=DATA_ONLY` and
  `LIVE_TRADING_ENABLED=false`.
- Stage 4B still has no Risk, Execution, signing, or order-authority import.
- Stages 1–4A commands, timers, and schema v1 are preserved.
- `3x-ui` is not in the diff.

## Finland deploy evidence

- Merged SHA deployed: `c49652565cd7ddab6432e3488ca73fa1c9c352b5`
- Release archive SHA-256:
  `1011dbc4026572ccf1f2fae82a534b38a6fda35dba41d6d082f4aceb70b70c80`
- Image: `polysia:c49652565cd7ddab6432e3488ca73fa1c9c352b5`
  (`sha256:a40174b91d0535b47deceba06975500feaae583050365afd76384d72487d24c5`)
- Pre-migration v3 backup:
  `wallet-intelligence-20260826T082746331668Z.sqlite3`, SHA-256
  `ec24a4e618b2e0e17b98ce0d558a57a79df870a6261e3f9b98a6432f2cac9e4a`
- Post-migration v4 backup:
  `wallet-intelligence-20260826T083658818909Z.sqlite3`, SHA-256
  `f0ab4f87ae758105ebe10143e18bc998db1b75a7887c9d9d103fe063d6474ebd`
- Runtime: `TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`, empty Live
  allowlist. Persistent worker active; oneshot timer disabled. Stages 1–3,
  Stage 4A, and history timers remain enabled.
- Smoke: ledger_balanced true; rolling 1h unknown ~0.24 versus cumulative ~0.55;
  mixed follower total P&L about `-397` with 113 open positions; Alpha NAV
  `999.55` and Stress NAV `999.81` after empty start; in-process poll mean
  `32.3s`, median `33.5s`, P95 `38.7s`. Confidence remains `LOW`.
- `3x-ui` restart count 0 and start time `2026-08-21T10:33:56Z` unchanged.
- Encrypted off-host backup remains absent. Shadow stays running.

## Follow-on: operational hardening (local evidence only)

Branch `codex/stage4b-operational-hardening` implements read/report isolation,
checkpoint-based latest-mark queries, sanitized failure categories/stages, and
split fresh/stale/missing mark counts. It does not change Strategy, Risk,
Execution, Live flags, schema version, journal mode, or indexes.

Local workstation gates on this branch (2026-08-26):

- `python scripts/validate_standards.py --mode full` — PASS, blocking=0
- `python -m compileall -q src tests` — PASS
- `python -m ruff check .` — PASS
- `python -m mypy src` — PASS, 173 source files
- `python -m pytest -q --basetemp=.pytest-review-tmp/stage4b-full` — PASS, 829 tests
- `python -m pip check` — PASS
- `python -m polysia.security.secret_scan` — PASS
- `python -m build` — PASS, `polysia-0.1.0` sdist and wheel
- `git diff --check` — PASS

This follow-on is **not** deployed. Helsinki remains on
`c49652565cd7ddab6432e3488ca73fa1c9c352b5` until the merged SHA is installed
with a verified pre-deploy backup. Server reporting-time and NRestarts evidence
will be recorded only after that deploy.
