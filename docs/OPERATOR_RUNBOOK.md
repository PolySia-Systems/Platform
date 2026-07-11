# PolySia — Polymarket Adapter — Operator Runbook

This runbook defines the safe operating order for the local Polymarket trading
system. Runtime-generated runbooks are available with:

```powershell
python -m polysia.cli operator-runbook
python -m polysia.cli operator-runbook --include-live
```

## Start Of Day

Run the safe local checks before collecting market data.

```powershell
python -m polysia.cli health
python -m polysia.cli deployment-readiness
python -m polysia.cli operator-status
```

Continue only when `health` is ok and readiness is ready. The output must never
show secrets, wallet addresses, allowlisted token values, or transaction hashes.

## Data Collection

Use public endpoints first.

```powershell
python -m polysia.cli discover-markets --limit 10
python -m polysia.cli stream-market --token-id YOUR_TOKEN_ID --max-events 5
```

Stop if public SDK or websocket errors repeat, or if normalized events look
wrong.

## Research Loop

Use only local paper execution for strategy checks.

```powershell
python -m polysia.cli paper-trade --token-id YOUR_TOKEN_ID --order-size 1
python -m polysia.cli backtest-jsonl --input .\events.jsonl --strategy stale-price
python -m polysia.cli backtest-jsonl --input .\events.jsonl --strategy passive-market-maker --min-edge 0.05
```

Continue only when risk decisions, fills, positions, and PnL are explainable and
reproducible.

## Reporting

Create a sanitized operator snapshot.

```powershell
python -m polysia.cli operator-report --format markdown
python -m polysia.cli operator-report --format html --output .\operator-report.html
```

## Live Dry-Run Only

Actual submit paths stay locked behind environment settings, allowlists, caps,
and explicit acknowledgement flags. Before any real submission, preview the
operation with dry-run commands.

```powershell
python -m polysia.cli live-open-orders --token-id YOUR_TOKEN_ID --i-understand-this-uses-live-account
python -m polysia.cli live-cancel-market-orders --token-id YOUR_TOKEN_ID --dry-run --i-understand-this-modifies-live-orders
python -m polysia.cli live-limit-order --token-id YOUR_TOKEN_ID --side BUY --price 0.01 --size 1 --dry-run --i-understand-this-places-real-orders
```

Stop if readiness is blocked, operator status reports warnings, caps are not
tiny, or dry-run output does not clearly show that no order was submitted.

## Emergency Stop

Return to a no-live-order state by setting `TRADING_MODE=DATA_ONLY`,
`LIVE_TRADING_ENABLED=false`, and removing the live token allowlist from the
active shell or deployment environment. Then run:

```powershell
python -m polysia.cli deployment-readiness
python -m polysia.cli operator-status
```

The expected result is that tiny live orders are not ready.
