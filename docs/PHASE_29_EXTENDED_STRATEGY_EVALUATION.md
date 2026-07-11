# Phase 29 Extended Strategy Evaluation

Phase 29 adds a read-only strategy evaluation command for larger replay,
paper, backtest, and real-data shadow artifacts. It summarizes strategy quality
without using the live broker, without submitting orders, and without canceling
orders.

Run it against the latest real-data shadow artifact:

```powershell
python -m pm_trader.cli strategy-evaluation-extended --input .\release-artifacts\shadow-run-real-data.json --output-dir .\release-artifacts
```

Generated artifacts:

- `release-artifacts/strategy-evaluation-extended.json`
- `release-artifacts/strategy-evaluation-extended.md`
- `release-artifacts/strategy-evaluation-extended.html`

The report includes:

- signal count, side counts, confidence, modeled edge, and signal frequency
- risk approvals, denials, sanitized denial buckets, exposure, position, and
  risk-limit utilization
- paper order count, fill count, fill ratio, missed fills, partial fills, and
  simulated slippage
- realized PnL, unrealized PnL, total PnL, max drawdown, win/loss count, and
  average PnL per simulated trade
- Brier score and probability buckets when outcome data is available
- clear warnings when outcomes or paper trades are unavailable

Safety rules:

- Read-only only.
- No live broker.
- No live order submit.
- No live order cancel.
- No live retry path.
- No strategy loop.
- Reports do not copy token IDs, wallet addresses, transaction hashes, private
  keys, API credentials, or signed payloads.
