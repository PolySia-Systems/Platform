# PolySia Platform Upgrade 006 Handoff

## Outcome

`POLYSIA-UPGRADE-006` establishes CPython 3.14.6 as PolySia's primary runtime,
keeps Python 3.11 and 3.13 support in CI, upgrades the official unified
Polymarket SDK to 0.2.0, refreshes all direct dependencies to their latest
compatible non-yanked releases reviewed on 2026-07-28, and replaces the
Windows-only pip baseline with an exact lock used by Windows and Linux CI.

No order, cancellation, transfer, authenticated mutation, strategy change,
risk-limit change, architecture-boundary change, credential-value change, or
live-control weakening occurred.

## Baseline and environment

| Item | Before | After |
|---|---|---|
| Starting Git baseline | `c3e0cdddefd437f8367d58a551658f887bd04a7e` | Upgrade branch based on that commit |
| Primary Python | `3.13.14` | `3.14.6` |
| Canonical environment | `PolySia` on Python 3.13 | `PolySia` on Python 3.14.6, promoted after verification |
| Temporary validation | None | `PolySia-py314-upgrade`, `PolySia-py314-repro` |
| Rollback | Prior recovery package | External Python 3.13 export with SHA-256 records |

Rollback export:

`C:\Users\Siamak\Documents\PolySia-backups\PolySia-py313-rollback-20260728-133429`

## Direct dependency changes

| Dependency | Before | After |
|---|---:|---:|
| hatchling | `>=1.25` | `1.31.0` |
| polymarket-client | `0.1.0b11` | `0.2.0` |
| pydantic | installed `2.13.4` | `>=2.13.4,<3` |
| pydantic-settings | installed `2.14.2` | `>=2.14.2,<3` |
| python-dotenv | installed `1.2.2` | `>=1.2.2,<2` |
| structlog | installed `26.1.0` | `>=26.1.0,<27` |
| rich | installed `15.0.0` | `>=15.0.0,<16` |
| typer | `0.26.8` | `0.27.0` |
| build | `1.5.1` (yanked) | `1.5.0` (latest non-yanked) |
| cyclonedx-bom | `7.3.0` | `7.3.1` |
| hypothesis | `6.156.6` | `6.163.0` |
| mypy | `2.1.0` | `2.3.0` |
| pip-audit | `2.10.1` | `2.10.1` |
| pre-commit | `4.6.0` | `4.6.1` |
| pytest | `9.1.1` | `9.1.1` |
| pytest-asyncio | `1.4.0` | `1.4.0` |
| ruff | `0.15.20` | `0.16.0` |
| setuptools | `82.0.1` | `83.0.0` |

Pip remains 26.1.2 and wheel remains 0.47.0. Direct versions were checked
against official PyPI metadata. Python 3.14.6 was verified against python.org.
SDK 0.2.0 and its compatibility changes were verified against the official
Polymarket PyPI project, repository, and changelog.

## SDK compatibility

All adapter-required public and secure client methods remain available. Market
and limit order signatures preserve PolySia's bounded parameters. Required
order-book, account, trade, order, fee, and market-state fields remain
available. The contract now explicitly verifies `condition_id`; the deprecated
`market` field remains accepted for compatibility.

No SDK type crossed the adapter boundary and no adapter runtime migration was
required beyond the approved version guard and contract assertion.

## Configuration and security

- Removed only deprecated `POLYMARKET_WALLET_ADDRESS` from the ignored private
  configuration.
- Preserved canonical `POLYMARKET_FUNDER_ADDRESS` and all credential values
  without displaying them.
- Redacted configuration status: ready, no conflicts, no missing
  authenticated-read variables.
- `setuptools==83.0.0` replaces vulnerable 82.0.1.
- Strict OSV result: no known vulnerabilities.
- CycloneDX JSON SBOM generated successfully under ignored `artifacts/`.

## Validation

- Focused SDK/adapter/execution/integration/property slice: 110 passed.
- Recreated environment contract check: 5 passed.
- Compile: passed.
- Ruff 0.16.0: passed.
- Mypy 2.3.0: passed over 119 source files.
- Pytest: 504 passed.
- `pip check`: passed.
- Secret scan: passed.
- Source and wheel build: passed.
- Isolated Python 3.14 wheel install and CLI smoke: passed.
- Strict OSV audit from the exact dependency lock: passed.
- CycloneDX SBOM generation: passed.
- Linux Python 3.14 build/test/wheel smoke: required in PR CI.
- Windows Python 3.11, 3.13, and 3.14: required in PR CI.

## Delivery and rollback

The upgrade is delivered through
`codex/python314-platform-upgrade`. The final PR URL, CI results, squash merge,
and synchronized main commit are resolved from GitHub history after this
handoff is committed.

Rollback is either:

1. revert the upgrade commit and recreate the previous Git-pinned baseline; or
2. recreate the external Python 3.13 rollback export.

Neither rollback path changes private credential values or venue state.

## Remaining limitation

Local validation ran on Windows. Linux compatibility is validated by the
dedicated GitHub Actions job; production server deployment, monitoring, and
operations remain out of scope. The next project task remains historical-data
acquisition and strategy validation, not more live trading.
