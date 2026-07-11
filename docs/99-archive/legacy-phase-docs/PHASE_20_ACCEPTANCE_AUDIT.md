# Phase 20 Acceptance Audit

Phase 20 adds a no-live-order acceptance audit and shadow-production workflow.
It is designed to prove that the local system path is wired correctly before
any later tiny-live review.

## Command

```powershell
python -m pm_trader.cli acceptance-audit
```

Optional arguments:

```powershell
python -m pm_trader.cli acceptance-audit `
  --duration-minutes 1 `
  --market-slug "optional-market-slug" `
  --token-id "optional-token-id" `
  --strategy stale-price `
  --output-dir release-artifacts `
  --markdown `
  --html `
  --json
```

## Safety Rules

- `LIVE_TRADING_ENABLED=true` always blocks the audit.
- `TRADING_MODE=LIVE` blocks unless `--allow-live-readonly` is explicitly used.
- The audit does not place live orders.
- The audit does not cancel live orders.
- The audit does not use the live broker.
- Reports contain only sanitized status, counts, metrics, and reasons.

## What It Checks

Safety checks:

- trading mode
- live flag
- kill switch state
- secret redaction
- optional clean git status
- `.env.example` safe defaults
- live guardrail presence

System checks:

- health payload availability
- deployment readiness
- release manifest availability
- operator runbook availability
- final handoff availability

Shadow-production checks:

- selected market/token shape
- mocked market stream integration
- normalized market events
- local orderbook updates
- stale stream detection availability
- reconnect supervisor availability
- strategy paper intents
- risk evaluation
- paper broker execution
- position and PnL updates
- no live broker usage

## Reports

The command writes reports under the selected output directory:

- `acceptance_audit.json`
- `acceptance_audit.md`
- `acceptance_audit.html`

If no format flags are passed, all three are written. If one or more of
`--json`, `--markdown`, or `--html` is passed, only the selected formats are
written.

## Final Result

The audit returns one of:

- `READY_FOR_SHADOW`
- `READY_FOR_TINY_LIVE`
- `NOT_READY`

`READY_FOR_TINY_LIVE` from this command is not permission to trade live. It
only means the acceptance-audit shadow path exercised strategy, risk, paper
execution, positions, and PnL without live trading. Later readiness gates still
control any tiny-live review.

