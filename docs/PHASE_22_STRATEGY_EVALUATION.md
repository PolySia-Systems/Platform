# Phase 22 Strategy Evaluation And Calibration

Phase 22 adds a read-only strategy evaluation command. It reviews outputs from
paper/backtest/shadow runs and produces sanitized JSON, Markdown, and HTML
reports. It does not connect to the live broker, place orders, approve live
trading, or change risk settings.

## Command

```powershell
python -m pm_trader.cli strategy-evaluation --input .\release-artifacts\shadow_run.json --output-dir .\release-artifacts
```

Optional flags:

```powershell
python -m pm_trader.cli strategy-evaluation `
  --input .\release-artifacts\shadow_run.json `
  --strategy stale-price `
  --output-dir .\release-artifacts `
  --min-sample-size 30 `
  --json `
  --markdown `
  --html
```

If no format flag is supplied, all three reports are written:

- `strategy_evaluation.json`
- `strategy_evaluation.md`
- `strategy_evaluation.html`

## Accepted Inputs

The evaluator accepts JSON or JSONL files shaped like:

- shadow-run reports
- replay/backtest results
- acceptance-audit style summaries
- paper logs
- JSONL event/result records with calibration fields

The evaluator reads only the fields needed for scoring and does not copy raw
input payloads into reports.

## Metrics

The report includes:

- signal quality: generated, approved, rejected, approval rate, rejection rate
- execution quality: paper orders, paper fills, fill rate, simulated slippage
- PnL quality: total/realized/unrealized paper PnL, drawdown, PnL per signal
- risk quality: rejection counts and rejection reason groups
- calibration: Brier score, probability buckets, and small sample warning

Copy-friendly formulas:

```text
brier_score = mean((p_model - outcome)^2)
expected_value = p_model - execution_price - cost_buffer
```

## Classification

The report classifies the strategy as one of:

- `STRATEGY_RESEARCH_ONLY`
- `STRATEGY_READY_FOR_SHADOW`
- `STRATEGY_READY_FOR_TINY_LIVE_REVIEW`
- `STRATEGY_NOT_READY`

This classification is for human review only. It never enables or approves
actual live trading.

## Safety

- No live API order path is used.
- No secrets, wallet values, token allowlist values, or raw environment values
  are written.
- Small sample sizes are explicitly warned about.
- Malformed input fails clearly instead of producing a misleading report.
