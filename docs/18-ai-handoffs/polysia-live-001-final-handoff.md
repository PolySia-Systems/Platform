# POLYSIA-LIVE-001 Final Handoff

## Objective and baseline

`POLYSIA-LIVE-001` required the smallest reusable venue-neutral Strategy
Registry, registration of one experimental BTC 15-minute strategy, and at most
one owner-authorized live entry only if every implementation, review, CI,
account, market, venue, and Risk gate passed.

The verified starting baseline was `main` and `origin/main` at
`bfc7eaddbde21271c5f9856e1962030e8c4959ff`. Two unrelated untracked
architecture prompt inputs were preserved unchanged.

## Implementation and merge

- Implementation branch: `codex/tiny-live-round-trip`.
- Pull Request: `https://github.com/Movafeghm/polysia/pull/10`.
- Final reviewed head: `f4ab8ccef41c68cb76cf499f7b96fe9f8c0f2c4f`.
- Squash merge: `ce24c848f73aa8c4b73beac3649fa483f3a97c86`.
- Runtime `main` and `origin/main` were synchronized before the real read-only
  preflight. The remote feature branch was deleted.

The implementation added:

- venue-neutral strategy definition, lifecycle, run, and performance models;
- a minimal Strategy Registry with SQLite persistence;
- `btc-15m-favorite-take-profit@0.1.0` as experimental,
  `bounded-micro-live`, and `unrated`;
- dynamic BTC Up/Down 15-minute market discovery and canonical order-book
  mapping;
- bounded portfolio admission and independent Risk authority, including the
  all-in notional-plus-fee `1.00` cap;
- persistent one-entry authorization and durable response/fill/position
  checkpoints;
- actual-fill-based GTC exit construction, partial-exit accounting, bounded
  ledger evidence, reconciliation safety controls, reports, and CLI wiring.

No dependency, SDK pin, credential, wallet behavior, or unrelated runtime path
was changed.

## Files changed by runtime Pull Request #10

The squash merge changed 31 files:

- `plans/active/first-evidence-sprint.md`
- `plans/active/tiny-live-round-trip-v1.md`
- `src/polysia/adapters/polymarket/mappers.py`
- `src/polysia/adapters/polymarket/public.py`
- `src/polysia/cli.py`
- `src/polysia/domain/market/__init__.py`
- `src/polysia/domain/market/models.py`
- `src/polysia/domain/strategy/__init__.py`
- `src/polysia/domain/strategy/models.py`
- `src/polysia/execution/tiny_live_round_trip.py`
- `src/polysia/monitoring/tiny_live_round_trip_report.py`
- `src/polysia/portfolio/__init__.py`
- `src/polysia/portfolio/live_admission.py`
- `src/polysia/risk/__init__.py`
- `src/polysia/risk/bounded_live.py`
- `src/polysia/storage/repositories.py`
- `src/polysia/storage/schemas.sql`
- `src/polysia/strategies/__init__.py`
- `src/polysia/strategies/btc_15m_favorite_take_profit.py`
- `src/polysia/strategies/registry.py`
- `tests/characterization/test_cli_contract.py`
- `tests/contract/test_polymarket_sdk_surface.py`
- `tests/integration/test_tiny_live_round_trip_vertical_slice.py`
- `tests/property/test_tiny_live_round_trip_properties.py`
- `tests/unit/adapters/test_polymarket_mappers.py`
- `tests/unit/adapters/test_polymarket_public.py`
- `tests/unit/execution/test_tiny_live_round_trip.py`
- `tests/unit/risk/test_bounded_live.py`
- `tests/unit/storage/test_db.py`
- `tests/unit/strategies/test_btc_15m_favorite_take_profit.py`
- `tests/unit/strategies/test_registry.py`

This documentation closeout updates `PROJECT_STATUS.md`, this handoff, and the
plan status only. Ignored account/run artifacts are not committed.

## Validation and review

Local validation in the `PolySia` environment passed:

- `python -m compileall -q src tests`;
- `python -m ruff check .`;
- `python -m mypy src` for 113 source files;
- `python -m pytest -q`: 418 passed;
- `python -m pip check`;
- `python -m polysia.security.secret_scan`;
- `python -m build` for source and wheel artifacts.

The final implementation head passed all six PR checks: Python 3.11 quality,
Python 3.13 quality, and strict OSV/SBOM supply-chain checks for both workflow
event runs. A later local OSV request could not reach the external feed; no
dependency changed and the final CI supply-chain jobs passed.

Independent re-review found and caused correction of partial-exit accounting,
all-in cap enforcement, crash durability, candidate fallback, fresh account
reads, stable internal order IDs, and the discovery-clock race. The final
re-review ran 69 relevant tests, Ruff, Mypy, and diff checks and reported no
blocking findings.

Post-merge `main` CI run `29182788976` passed for
`ce24c848f73aa8c4b73beac3649fa483f3a97c86`: quality on Python 3.11 and 3.13
plus strict OSV audit and SBOM generation.

## Actual read-only preflight

- Run ID: `aa060a47-03ed-449b-8001-5ec1f8209327`.
- Runtime commit: `ce24c848f73aa8c4b73beac3649fa483f3a97c86`.
- Mode: dry-run; no submit flag or acknowledgement was supplied.
- Authenticated API connectivity and configured account identity were verified.
- Balance and allowance were readable and sufficient. Exact confidential
  values remain only in ignored local evidence.
- Open-order and position reads succeeded. No open order was observed;
  pre-existing positions were left unchanged and are not identified here.
- The actual geoblock endpoint returned allowed.
- Public market inspected: `btc-updown-15m-1783837800`, active and accepting
  orders at the read time.
- Strategy result: `NO_TRADE`.
- Exact stop reason: `venue minimum order size cannot be satisfied within the
  1.00 cap`.

This is a mandatory pre-entry stop condition. The cap was not increased and no
Risk, venue, geographic, acknowledgement, allowlist, or duplicate-prevention
control was bypassed.

## Live-run and order lifecycle result

- Real submit invocation: not performed because not every gate passed.
- Live entry attempts: zero.
- Entry order: none.
- Entry fill: none.
- Exit order: none.
- Actual task fees: zero.
- Task-created position or exposure: none.
- Cancellation or cleanup mutation: none required.
- Final classification: `NO_TRADE`.

The local database recorded one StrategyRun for the read-only preflight, zero
live order checkpoints, zero run ledger events, and zero authorization claims
for `POLYSIA-LIVE-001`.

## Reconciliation

Reconciliation was not entered because the strategy stopped before producing
an executable intent and before the persistent authorization claim. Therefore
there was no task order, fill, position transition, fee, or external state to
reconcile. Account state remained read-only and the task created no open order
or exposure.

## Evidence

Ignored local evidence directory:

`release-artifacts/tiny-live-round-trip/aa060a47-03ed-449b-8001-5ec1f8209327/`

- JSON: `tiny-live-round-trip.json`
- JSON SHA-256:
  `74906A604BDE601E2BEDD9513794894DA8416C1FE7483A00C14535B71534EB0C`
- Markdown: `tiny-live-round-trip.md`
- Markdown SHA-256:
  `EF84476AB77BE160FE5225E27A27B16DED913475FC55051C5CCD6EC92E9B531C`
- SQLite evidence: ignored local `data/polysia.sqlite3`

No live artifact, account identifier, credential, balance value, or position
identifier is committed.

## Acceptance criteria disposition

| # | Result | Evidence |
|---|---|---|
| 1-5 | PASS | Venue-neutral registry and strategy contracts; Strategy cannot execute; Risk remains final authority. |
| 6-8 | PASS | All-in `1.00` cap, persistent one-entry claim, and no retry/replacement behavior have tests. |
| 9-11 | PASS | Actual account and public market reads completed; market, fee, liquidity, freshness, venue-rule, and geoblock gates are implemented. |
| 12-14 | PASS IN CODE | Actual-fill exit arithmetic, reconciled quantity, persistence, ledger, and reconciliation are tested; the real preflight stopped before an order. |
| 15 | PASS | 418 local tests and all required implementation CI checks passed. |
| 16 | PASS | Final independent re-review reported no blockers. |
| 17 | PASS | Runtime was squash-merged and `main` synchronized before preflight. |
| 18 | PASS, NO ATTEMPT | The authorization allowed one attempt only if every gate passed; the venue minimum failed, so zero attempts was the required behavior. |
| 19 | PASS | Result is honestly classified `NO_TRADE`. |
| 20 | PASS ON DOC MERGE | `PROJECT_STATUS.md`, plan status, and this handoff are updated in the documentation PR. |

## Limitations and open decisions

- The current venue minimum and fixed `1.00` authorization are incompatible for
  the inspected market. A new attempt or higher cap requires a separate owner
  decision and new authorization; this task must not be retried.
- Restart behavior is fail-closed and blocks a duplicate entry, but it does not
  automatically resume or place a missing exit after a confirmed-fill crash.
  Explicit recovery and operator reconciliation are required before broader
  limited-live reuse.
- The registered strategy remains experimental and unrated. This execution-path
  task provides no profitability evidence.
- The approved SDK remains `polymarket-client==0.1.0b11`; PR #5 remains on HOLD.

## Rollback

Revert squash merge `ce24c848f73aa8c4b73beac3649fa483f3a97c86` to
remove the runtime slice. The additive SQLite tables can remain unused; no
destructive migration is required. The preflight created no external order or
position, so no account rollback or cancellation is needed. Keep ignored local
evidence until the owner approves archival or removal.

## Exact recommended next task

Implement and independently review a fail-closed post-fill recovery and
operator-reconciliation slice for the bounded round-trip runner. It must load
durable checkpoints and actual read-only account state, classify interrupted
entry/exit states, produce a deterministic operator action plan, and prevent
duplicate entry or automatic replacement orders. Validate only with
deterministic crash/restart, partial-fill, and authenticated read-only checks.
Do not perform another live attempt, change the `1.00` cap, upgrade the SDK, or
add generalized orchestration.
