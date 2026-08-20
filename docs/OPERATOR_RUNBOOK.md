# PolySia — Polymarket Adapter — Operator Runbook

This runbook defines the safe operating order for the local Polymarket trading
system. Runtime-generated runbooks are available with:

```powershell
python -m polysia.cli system runbook
python -m polysia.cli system runbook --include-live
```

## Start Of Day

Run the safe local checks before collecting market data.

```powershell
python -m polysia.cli system health
python -m polysia.cli system configuration
python -m polysia.cli ops deployment-readiness
python -m polysia.cli system status
```

Continue only when `health` is ok and readiness is ready. The output must never
show secrets, wallet addresses, allowlisted token values, or transaction hashes.

`configuration-status` must also be `ready` for the intended operation. If it
reports both `POLYMARKET_FUNDER_ADDRESS` and deprecated
`POLYMARKET_WALLET_ADDRESS`, stop authenticated/live work. Remove the deprecated
variable only through an owner-reviewed configuration change, then rerun the
redacted status command. Do not print either value while diagnosing the issue.

## Windows Clock Synchronization

PolySia reads the official CLOB server time before the current authenticated
round-trip path and fails closed when absolute drift exceeds
`POLYMARKET_MAX_CLOCK_DRIFT_SECONDS` (maximum allowed value: 5 seconds). It does
not change Windows services or the system clock.

Inspect Windows time state without changing it:

```powershell
Get-Service W32Time
w32tm /query /status
w32tm /query /source
w32tm /stripchart /computer:time.windows.com /dataonly /samples:5
```

If the clock is not synchronized, stop authenticated and live operations. The
operator may enable **Set time automatically** and select **Sync now** under
Windows **Settings > Time & language > Date & time**. An administrator may
instead run `w32tm /resync` after confirming the intended time source. PolySia
must never perform either action automatically.

After manual synchronization, rerun:

```powershell
python -m polysia.cli system configuration
python -m polysia.cli live tiny-round-trip --dry-run
```

Continue only when the clock preflight reports `pass`. A timeout, missing server
time, unreadable response, or excessive positive or negative drift is blocking.

## Data Collection

Use public endpoints first.

```powershell
python -m polysia.cli market discover --limit 10
python -m polysia.cli market stream --token-id YOUR_TOKEN_ID --max-events 5
```

Stop if public SDK or websocket errors repeat, or if normalized events look
wrong.

## Research Loop

Use only local paper execution for strategy checks.

```powershell
python -m polysia.cli research paper-trade --token-id YOUR_TOKEN_ID --order-size 1
python -m polysia.cli research backtest --input .\events.jsonl --strategy stale-price
python -m polysia.cli research backtest --input .\events.jsonl --strategy passive-market-maker --min-edge 0.05
```

Continue only when risk decisions, fills, positions, and PnL are explainable and
reproducible.

## Reporting

Create a sanitized operator snapshot.

```powershell
python -m polysia.cli system report --format markdown
python -m polysia.cli system report --format html --output .\operator-report.html
```

## Read-Only Live Lifecycle Recovery

For a previously authorized persisted round trip, use the dedicated read-only
commands. They may read authenticated venue state and update local reconciliation
or alert records, but they cannot submit, cancel, replace, or retry an order.

Run one reconciliation observation:

```powershell
python -m polysia.cli ops reconcile-live-round-trip `
  --run-id YOUR_RUN_ID `
  --authorization-id YOUR_CONSUMED_AUTHORIZATION_ID
```

Run one scheduler-friendly monitoring cycle:

```powershell
python -m polysia.cli ops monitor-live-round-trip `
  --run-id YOUR_RUN_ID `
  --authorization-id YOUR_CONSUMED_AUTHORIZATION_ID `
  --max-cycles 1
```

Bounded polling supports at most ten cycles and a minimum 30-second interval.
Use an external scheduler only after an explicit operational decision. Stop on
`blocked`, `CRITICAL`, identity/configuration conflict, geoblock, clock drift,
unreadable account state, or unexplained position/fill/ledger mismatch. Never
respond to a reconciliation warning by placing a replacement order manually
without separate owner authorization and a new task.

## Live Dry-Run Only

Actual submit paths stay locked behind environment settings, allowlists, caps,
and explicit acknowledgement flags. Before any real submission, preview the
operation with dry-run commands.

```powershell
python -m polysia.cli live open-orders --token-id YOUR_TOKEN_ID --i-understand-this-uses-live-account
python -m polysia.cli live cancel-market-orders --token-id YOUR_TOKEN_ID --dry-run --i-understand-this-modifies-live-orders
python -m polysia.cli live limit-order --token-id YOUR_TOKEN_ID --side BUY --price 0.01 --size 1 --dry-run --i-understand-this-places-real-orders
```

Stop if readiness is blocked, operator status reports warnings, caps are not
tiny, or dry-run output does not clearly show that no order was submitted.

## Emergency Stop

Return to a no-live-order state by setting `TRADING_MODE=DATA_ONLY`,
`LIVE_TRADING_ENABLED=false`, and removing the live token allowlist from the
active shell or deployment environment. Then run:

```powershell
python -m polysia.cli ops deployment-readiness
python -m polysia.cli system status
```

The expected result is that tiny live orders are not ready.
