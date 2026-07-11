# Phase 24 Tiny Live Readiness

Phase 24 adds a conservative readiness gate for any future tiny-live review.
It does not place live orders, does not cancel live orders, and does not enable
live trading.

## Command

```powershell
python -m pm_trader.cli tiny-live-readiness --output-dir .\release-artifacts
```

Optional explicit report paths:

```powershell
python -m pm_trader.cli tiny-live-readiness `
  --acceptance-audit .\release-artifacts\acceptance_audit.json `
  --shadow-run .\release-artifacts\shadow_run.json `
  --strategy-evaluation .\release-artifacts\strategy_evaluation.json `
  --fill-simulation-audit .\release-artifacts\fill_simulation_audit.json `
  --output-dir .\release-artifacts
```

If no format flag is supplied, all three reports are written:

- `tiny_live_readiness.json`
- `tiny_live_readiness.md`
- `tiny_live_readiness.html`

## Aggregated Inputs

The command aggregates:

- deployment readiness
- release manifest/final handoff availability
- acceptance audit
- shadow run
- strategy evaluation
- fill simulation audit
- live guardrail status
- geoblock enforcement status
- signer/funder diagnostics availability
- kill switch availability
- token allowlist status
- tiny cap configuration
- secret redaction status

## Final Result

The report returns one of:

- `READY_FOR_TINY_LIVE_REVIEW`
- `READY_FOR_TINY_LIVE_DRY_RUN_ONLY`
- `NOT_READY_FOR_TINY_LIVE`

Warnings produce dry-run-only readiness. Failures block tiny-live readiness.

## Mandatory Safety Checks

The gate verifies:

- default mode is still `DATA_ONLY`
- `LIVE_TRADING_ENABLED=false` remains the default
- current readiness run does not enable live trading
- geoblock enforcement exists and fails closed
- kill switch can block
- live token allowlist is required for actual live use
- tiny caps are conservative
- live orders require explicit acknowledgement
- strategies do not directly reference live execution paths
- signer/funder separation is documented
- sanitized signer/funder diagnostics are available
- reports do not contain configured sensitive values

## Safety Statement

This command is only a readiness gate. It never submits an order, never cancels
an order, and never changes the live-trading state.
