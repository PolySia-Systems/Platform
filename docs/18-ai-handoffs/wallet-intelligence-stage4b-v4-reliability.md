# Stage 4B v4 reliability, observability, and Shadow worker

## Status

HISTORICAL. This is the accepted schema-v4 reliability record. Its successor
schema-v5 ownership record is
[`stage4b-data-ownership-cutover.md`](stage4b-data-ownership-cutover.md); current
schema-v6 lifecycle evidence is
[`stage4b-data-lifecycle-v1.md`](stage4b-data-lifecycle-v1.md).
PR `#101` merged as `41221e7edef56faeccfe5783a22415956c7ffddf` and was deployed on
`Hetzner-Finland-Helsinki-01` in DATA_ONLY/Shadow. Reporting isolation from PR
`#94`, the Compose lifecycle from PR `#96`, and contention hardening from PRs
`#98`–`#101` remain historical foundations. No real order was sent. `3x-ui`
was not restarted.

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
- `python -m pip_audit --strict --vulnerability-service osv` — FAIL on a
  workstation-only orphan package absent from PolySia lockfiles
  (PYSEC-2026-3552/3553/3554 and GHSA-537c-gmf6-5ccf). This change does not
  modify lockfiles. CI supply-chain runs only when dependency files change.

## Safety

- Compose and systemd keep `TRADING_MODE=DATA_ONLY` and
  `LIVE_TRADING_ENABLED=false`.
- Stage 4B still has no Risk, Execution, signing, or order-authority import.
- Stages 1–4A commands, timers, and schema v1 are preserved.
- `3x-ui` is not in the diff.

## Finland deploy evidence (PR `#92` schema v4)

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

## Follow-on: operational hardening (PR `#94`, deployed)

PR `#94` merged as `b867408b5176541f3168767380d4a1e25b80f740` and is installed
on Helsinki. The change isolates read/report from live SQLite, uses
checkpoint-based latest-mark queries, persists sanitized failure
categories/stages, and splits fresh/stale/missing mark counts. It does not
change Strategy, Risk, Execution, Live flags, schema version, journal mode, or
indexes.

Local workstation gates on the implementation commit `857c8e4` (2026-08-26):

- `python scripts/validate_standards.py --mode full` — PASS, blocking=0
- `python -m compileall -q src tests` — PASS
- `python -m ruff check .` — PASS
- `python -m mypy src` — PASS, 173 source files
- `python -m pytest -q --basetemp=.pytest-review-tmp/stage4b-full` — PASS, 829 tests
- `python -m pip check` — PASS
- `python -m polysia.security.secret_scan` — PASS
- `python -m build` — PASS, `polysia-0.1.0` sdist and wheel
- `git diff --check` — PASS

### Finland deploy evidence (PR `#94`)

- Merged SHA deployed: `b867408b5176541f3168767380d4a1e25b80f740`
- Release path: `/opt/polysia-releases/b867408b5176541f3168767380d4a1e25b80f740`
- Image: `polysia:b867408b5176541f3168767380d4a1e25b80f740`
  (`sha256:2c2eb304011f7b17b2f31ac19656aaf890b81d5b73bd6266f48cb625d6ec502b`)
- Pre-deploy backup:
  `wallet-intelligence-20260826T124243669316Z.sqlite3`, SHA-256
  `7c12c5659eadfe8b01fc4d81cc2375a85f1bae533cc18f52e13851f92db89ed8`
- Post-switch backup (worker stopped during switch, same digest):
  `wallet-intelligence-20260826T124405389067Z.sqlite3`, 268 943 360 bytes
- Runtime: `TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`. Persistent
  worker active; oneshot timer disabled.
- Artifact health (30 host reads while worker ran): 0.0001–0.0002 s. No
  `database is locked` lines. `NRestarts` stayed 0 through 15 in-worker CLI
  health calls and 180 s observation.
- Snapshot `ContinuousShadowRepository.results(limit=100)`: 1.811 s. Host
  SQL on the backup: evaluations 0.086 s / 7849 rows; latest-mark join
  0.000 s / 47 rows; remaining profiled queries under 0.05 s.
- CLI `python -m polysia.cli` import in the image: 5.916 s. Full
  `portfolio-results` CLI wall including import: 10.695 s. Indexes were not
  added because SQLite was not the 5 s bottleneck.
- At 12:59:06 UTC a validation `docker compose run` one-shot removal dropped
  the Compose veth and the `compose run` worker exited status 1. systemd
  restarted it (`NRestarts` 1, `OOMKilled=false`). The in-flight poll recorded
  `source_unavailable` at 12:59:05 UTC. After recovery: `ledger_balanced=true`,
  `duplicate_processing_count=0`, `last_poll_status=succeeded`, marks
  fresh/stale/missing 168/82/0, no real order.
- `3x-ui` restart count 0 and start time `2026-08-21T10:33:56Z` unchanged.

### Remaining work

- Eager CLI imports still add about 6 s before snapshot results. A lazy-import
  CLI split is not in this SHA. Host artifact health and `results()` on a
  verified snapshot remain the measured sub-second / sub-five-second paths.
- Encrypted off-host backup remains absent. Confidence remains `LOW`.

### Finland deploy evidence (PR `#96`)

- Merged SHA deployed: `abb96570ba0e27deb163688e1fe25f8d0fefe9b8`
- Release path: `/opt/polysia-releases/abb96570ba0e27deb163688e1fe25f8d0fefe9b8`
- Image: `polysia:abb96570ba0e27deb163688e1fe25f8d0fefe9b8`
  (`sha256:761ba8f1fbe19908744a8a39cb80cd019821c59e24b56b5457ad330cee58cb29`)
- Pre-switch backup:
  `wallet-intelligence-20260826T133450Z.sqlite3`, SHA-256
  `cb1903d098b98050881976e6648be441aac99a3fe3e88b65229bcf6e230b3e9e`
- Worker unit now `docker compose up --abort-on-container-exit`. `NRestarts=0`
  after start. A concurrent `compose run --rm` health of
  `wallet-intelligence-sync` did not increase `NRestarts`.
- Artifact reads 0.0000–0.0003 s. `ledger_balanced=true`,
  `duplicate_processing_count=0`, `TRADING_MODE=DATA_ONLY`,
  `LIVE_TRADING_ENABLED=false`.
- `3x-ui` restart count 0 and start time `2026-08-21T10:33:56Z` unchanged.

## Final contention-hardening closeout (PRs `#98`–`#101`)

The repair was completed as four small, evidence-driven changes. PR `#98`
introduced bounded SQLite busy classification. PR `#99` removed repeated
per-poll store initialization, corrected systemd/Compose lifecycle handling,
kept health reporting fail-soft, and corrected backlog-age semantics. PR `#100`
made only `source_unavailable`, `market_read_failed`, and `sqlite_busy`
retryable inside the persistent loop. PR `#101` added the missing outer poll
boundary so raw storage failures raised while loading experiment or candidate
state are classified as `sqlite_busy/load_state` before they can terminate the
process. Persistence, lease, and unexpected failures still fail closed.

Two intermediate deployments exposed remaining boundaries and were deliberately
superseded. This is positive runtime evidence, not hidden success-only history.
The final PR `#101` head passed the normal quality gates, including 837 tests,
and GitHub Actions run `33026629181` completed successfully.

### Final deployment and recovery evidence

- Merge and deployed SHA:
  `41221e7edef56faeccfe5783a22415956c7ffddf`
- Release path:
  `/opt/polysia-releases/41221e7edef56faeccfe5783a22415956c7ffddf`
- Release archive SHA-256:
  `b41f56d58797a44145b54481cfeb93b137492fa1e1f67622920cfb9aeef6d2f6`
- Image ID:
  `sha256:d0486bacd1bf76ad5d5e40201c6315a50c561d117a703c7a40d8ab8676d4b8fe`
- Pre-switch backup:
  `wallet-intelligence-20260827T040936773971Z.sqlite3`, SHA-256
  `ac1a43fe46c346d0225479de3d355fc5a9a09589a092659f414bd952e7bb3c8d`
- Final online backup:
  `wallet-intelligence-20260827T045026736563Z.sqlite3`, 481,038,336 bytes,
  SHA-256 `df1552b4c44b869100cd959689f5cf451939c2d073402e808fd954aee3eb9347`
- Both restore checks passed checksum, SQLite integrity, foreign keys, schema,
  and row-count validation.

The final worker started at 04:14:30 UTC. Natural Stage 4A cycles started at
04:20:14, 04:30:12, and 04:40:11 UTC and all finished successfully. Across
those overlaps the worker recorded two classified SQLite busy skips and one
classified source-unavailable skip, then continued normally. The final online
backup added one more classified busy skip. No raw `database is locked`
traceback occurred, `NRestarts` remained zero, and duplicate processing stayed
zero. This proves bounded recovery for the observed single-host SQLite
contention class; it does not claim that contention can never occur.

Snapshot evidence at 04:50 UTC:

- 1,927 successful polls, 5,640 unique events, and 1,941 overlap duplicates;
- 13,840 evaluations: 2,393 simulated, 5,511 rejected, and 5,936 unknown;
- 554 verified settlements and 23 current settlement-backlog items;
- Decimal identity delta `-1E-25`, unmarked-adjusted delta `-1E-25`, and
  `ledger_balanced=true`;
- 247 open positions and `real_orders=false`;
- mixed modeled P&L `-495.81`, Alpha `-46.33`, and Stress `-276.37`, all
  low-confidence and not decision-ready.

Fresh interval telemetry recorded zero rate limits, zero cooldowns, zero
retries, a closed circuit, and maximum trade scheduling delay below 0.67 s.
The atomic report remained `warning` for genuine stale marks and settlement
backlog. Safety remained `TRADING_MODE=DATA_ONLY` and
`LIVE_TRADING_ENABLED=false`; no Risk, Execution, signing, or Live service ran.
`3x-ui` retained identity `ab567d6d…`, restart count zero, and start time
2026-08-21 10:33:56 UTC.
