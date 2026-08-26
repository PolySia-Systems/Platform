# Stage 4B v4 reliability, observability, and Shadow worker

## Status

Repository implementation is complete on `codex/stage4b-shadow-reliability`.
Merge, Finland deploy of the exact merged SHA, and post-deploy observation are
separate remaining operator steps recorded below as pending until verified.

This change does not enable Live trading and does not send orders.

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

## Pending after merge

1. Merge only after required GitHub checks pass.
2. Deploy the exact merged SHA to `Hetzner-Finland-Helsinki-01` as an immutable
   archive because repository Deploy Keys are disabled.
3. Backup the wallet-intelligence database before the v4 migrate, rehearse a
   disposable restore, then disable the Stage 4B timer and enable the persistent
   service.
4. Verify DATA_ONLY, Live false, zero real orders, Decimal identity, worker
   health, Stages 1–4, latency, rolling health, Alpha/Stress isolation,
   settlement attribution, rate-limit telemetry, mark freshness, and unchanged
   `3x-ui` identity/uptime/restart count.
5. Observe long enough for a smoke comparison. Do not treat a short window as
   profit evidence. Keep Shadow running.
