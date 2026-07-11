# Phase 23 Fill Simulation Accuracy

Phase 23 adds a read-only fill simulation audit. It compares deterministic
paper fill models against orderbook conditions so paper execution can be judged
before any future tiny-live review.

The audit does not use the live broker, does not place orders, does not cancel
orders, and does not approve live trading.

## Command

```powershell
python -m pm_trader.cli fill-simulation-audit --input .\backtest_result.json --output-dir .\release-artifacts
```

Optional repeated model selection:

```powershell
python -m pm_trader.cli fill-simulation-audit `
  --input .\backtest_result.json `
  --model conservative `
  --model top-of-book `
  --model queue-aware `
  --output-dir .\release-artifacts
```

If no format flag is supplied, all three reports are written:

- `fill_simulation_audit.json`
- `fill_simulation_audit.md`
- `fill_simulation_audit.html`

## Fill Models

Conservative:

- BUY fills only when limit price is greater than or equal to best ask.
- SELL fills only when limit price is less than or equal to best bid.
- Fill price is the top-of-book price.
- Partial fills are allowed only when visible depth is smaller than order size.

Top-of-book:

- Uses only best bid/ask and top-level size.
- Tracks filled, partially filled, and missed orders.
- Does not infer hidden liquidity.

Queue-aware:

- Uses visible top-of-book depth.
- Applies a deterministic queue penalty before fill size is calculated.
- Supports partial fills.
- Remains deterministic for repeatable tests.

## Metrics

The report includes:

- simulated order count
- simulated fill count
- fill rate
- partial fill count
- missed fill count
- average fill price
- average slippage
- max slippage
- average time-to-fill if available
- paper PnL by fill model
- PnL difference across fill models
- conservatism score
- warning if a model is more optimistic than conservative baseline

## Classification

The audit returns one of:

- `FILL_MODEL_CONSERVATIVE_OK`
- `FILL_MODEL_NEEDS_MORE_DATA`
- `FILL_MODEL_TOO_OPTIMISTIC`
- `FILL_MODEL_NOT_READY`

The classification is conservative and is for human review only. It does not
enable live trading.

## Safety

- No live API order path is used.
- No secrets or raw environment values are written.
- No wallet, funder, or token allowlist values are required.
- Reports contain derived metrics, not raw secret-bearing runtime state.
