# Polymarket Operator Runbook

This runbook is generated from sanitized runtime checks. It does not include private keys, wallet addresses, allowlisted token values, or raw live order responses.

## Current Gate Status

- Operator status: blocked
- Deployment readiness: ready
- Tiny live orders ready: False
- Readiness failures: 0
- Generated at: 2026-07-06T09:08:17.766212+00:00

## 1. Start Of Day

Confirm the local environment is safe before collecting data.

### Commands

- `python -m pm_trader.cli health`
- `python -m pm_trader.cli deployment-readiness`
- `python -m pm_trader.cli operator-status`

### Checks

- health returns status ok
- deployment-readiness returns status ready
- operator-status does not expose secrets or wallet addresses

### Stop Conditions

- deployment-readiness is blocked
- operator-status reports an unexpected live-ready state

## 2. Data Collection

Inspect public markets and stream one token without trading.

### Commands

- `python -m pm_trader.cli discover-markets --limit 10`
- `python -m pm_trader.cli stream-market --token-id YOUR_TOKEN_ID --max-events 5`

### Checks

- market discovery returns active markets
- stream-market prints normalized JSON lines

### Stop Conditions

- public SDK or websocket errors repeat
- received events cannot be normalized

## 3. Research Loop

Test strategies only through paper trading and replay backtests.

### Commands

- `python -m pm_trader.cli paper-trade --token-id YOUR_TOKEN_ID --order-size 1`
- `python -m pm_trader.cli backtest-jsonl --input .\events.jsonl --strategy stale-price`
- `python -m pm_trader.cli backtest-jsonl --input .\events.jsonl --strategy passive-market-maker --min-edge 0.05`

### Checks

- paper-trade uses the local paper broker
- backtests finish without live API calls
- fills, positions, and PnL are explainable before any live dry-run

### Stop Conditions

- risk decisions are unexpected
- paper results cannot be reproduced from the same input

## 4. Reporting

Create a sanitized operator snapshot for review.

### Commands

- `python -m pm_trader.cli operator-report --format markdown`
- `python -m pm_trader.cli operator-report --format html --output .\operator-report.html`

### Checks

- report includes only configured/not-configured booleans and counts
- report does not print secrets, wallet addresses, token values, or hashes

### Stop Conditions

- None

## 5. Live Dry-Run Only

Preview tiny live operations before any actual submission.

### Commands

- `python -m pm_trader.cli live-open-orders --token-id YOUR_TOKEN_ID --i-understand-this-uses-live-account`
- `python -m pm_trader.cli live-cancel-market-orders --token-id YOUR_TOKEN_ID --dry-run --i-understand-this-modifies-live-orders`
- `python -m pm_trader.cli live-limit-order --token-id YOUR_TOKEN_ID --side BUY --price 0.01 --size 1 --dry-run --i-understand-this-places-real-orders`

### Checks

- TRADING_MODE is LIVE only when intentionally set by the operator
- LIVE_TRADING_ENABLED is true only for deliberate live testing
- the token is allowlisted and caps remain tiny
- dry-run output shows submitted false

### Stop Conditions

- readiness is blocked
- operator-status reports warnings
- any live command would move beyond dry-run before the operator is ready

## Emergency Stop

Return the system to a no-live-order state.

### Commands

- Set TRADING_MODE=DATA_ONLY for the active shell or deployment environment.
- Set LIVE_TRADING_ENABLED=false for the active shell or deployment environment.
- Remove POLYMARKET_LIVE_TOKEN_ALLOWLIST from the active shell or deployment environment.
- Run python -m pm_trader.cli deployment-readiness again.

### Checks

- deployment-readiness remains ready or clearly explains blocked checks
- operator-status reports tiny_live_orders_ready false
- no live cancel or submit command is run without explicit acknowledgement

### Stop Conditions

- environment values cannot be confirmed
- open live orders need manual review before cancellation
