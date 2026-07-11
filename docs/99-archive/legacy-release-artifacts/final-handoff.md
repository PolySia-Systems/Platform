# Polymarket Final Handoff

This handoff is generated from sanitized local checks. It does not include private keys, wallet addresses, allowlisted token values, transaction hashes, or raw live order responses.

## Status

- Final handoff status: ready
- Deployment readiness: ready
- Geoblock readiness: pass
- Release manifest: ready
- Package: polymarket-trading-system 0.1.0
- CLI entrypoint: pm_trader.cli:app
- Git branch: delivery/phase-36-python-sdk
- Git commit: c81c084
- Git clean: True
- Generated at: 2026-07-06T09:08:17.767978+00:00

## Quality Gates

- tests: pass (`python -m pytest`)
- lint: pass (`python -m ruff check .`)
- typecheck: pass (`python -m mypy src`)

## Generated Artifacts

- deployment_automation: `release-artifacts\deployment-automation.json`
- operator_runbook: `release-artifacts\operator-runbook.md`
- release_manifest: `release-artifacts\release-manifest.json`

## Safe Operating Baseline

- Default runtime mode remains DATA_ONLY.
- Live submission remains disabled unless LIVE mode and explicit enable flags are set.
- Live submit and cancel operations remain token-allowlist gated.
- Tiny live order caps remain enforced by settings and risk checks.
- Live order placement is blocked unless the official Polymarket geoblock endpoint returns blocked=false.
- Paper trading, replay backtests, reports, runbooks, and manifests do not call live trading APIs.

## Final Operator Commands

- `python -m pm_trader.cli health`
- `python -m pm_trader.cli deployment-automation --require-clean-git --include-live-runbook`
- `python -m pm_trader.cli operator-runbook --include-live`
- `python -m pm_trader.cli release-manifest --require-clean-git`
- `python -m pm_trader.cli post-live-reconciliation --output-dir .\release-artifacts`
- `python -m pm_trader.cli observability-snapshot --output-dir .\release-artifacts`
- `python -m pm_trader.cli shadow-run-real-data --auto-btc-5m --max-events 100 --output-dir .\release-artifacts`
- `python -m pm_trader.cli strategy-evaluation-extended --input .\release-artifacts\shadow-run-real-data.json --output-dir .\release-artifacts`
- `python -m pm_trader.cli tiny-live-monitor --output-dir .\release-artifacts --redact-secrets`
- `python -m pm_trader.cli controlled-second-tiny-live --auto-btc-5m --side BUY --outcome YES --max-notional 1.00 --order-type FOK --dry-run --output-dir .\release-artifacts`
- `python -m pm_trader.cli production-gap-audit --output-dir .\release-artifacts`
- `python -m pm_trader.cli main-merge-review --output-dir .\release-artifacts`
- `python -m pm_trader.cli local-release-closeout --output-dir .\release-artifacts`
- `python -m pm_trader.cli reconcile-account --output-dir .\release-artifacts`
- `python -m pm_trader.cli manual-intervention-live-test --auto-btc-5m --outcome YES --side BUY --max-notional 1.00 --order-type FOK --dry-run --output-dir .\release-artifacts`

## Stop Conditions

- Any quality gate fails.
- Deployment readiness or release manifest is blocked.
- Generated output contains secret values, wallet addresses, token values, or transaction hashes.
- A live workflow would move beyond dry-run before manual operator approval.
