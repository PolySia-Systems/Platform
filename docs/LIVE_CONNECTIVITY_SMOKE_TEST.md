# Live Connectivity Smoke Test Notes

This note captures the July 1, 2026 live-connectivity debugging result so the
same signer/funder issue can be solved quickly in this project or reused as a
pattern in another Polymarket project.

## What Failed

The new project connected to the authenticated SDK, but the real 1 USDC smoke
order aborted before placement. The account path showed no usable balance or
approval, even though an older `py-clob-client-v2` project had already placed a
guarded real 1 USDC FOK market BUY successfully.

The useful clue from the older project was the wallet split:

```text
signer = login EOA private key
funder = Polymarket trading proxy wallet
```

Using the login EOA wallet address as `POLYMARKET_FUNDER_ADDRESS` is wrong for
this account type and can cause signer/API-key or balance/approval confusion.

## Correct Rule

Keep these values separate:

- `POLYMARKET_PRIVATE_KEY`: signer/login EOA private key.
- `POLYMARKET_FUNDER_ADDRESS`: Polymarket trading proxy/funder wallet.
- `POLYMARKET_SIGNATURE_TYPE=3`: useful compatibility/diagnostic setting for
  this wallet style.

For the new `polymarket-client` SDK, initialize the secure client with:

```python
AsyncSecureClient.create(
    private_key=POLYMARKET_PRIVATE_KEY,
    wallet=POLYMARKET_FUNDER_ADDRESS,
)
```

The new SDK then detects the wallet type and derives the order signature type.
Do not pass the signer/login EOA address as the SDK `wallet` value for this
test account.

## Fixed In This Project

The secure adapter now:

- prefers `POLYMARKET_FUNDER_ADDRESS` as the active SDK wallet;
- falls back to legacy `POLYMARKET_WALLET_ADDRESS` only when no funder is set;
- reports sanitized signer/funder diagnostics through `live-account-status`;
- never prints raw private keys, API keys, funder addresses, or wallet
  addresses;
- requires `POLYMARKET_FUNDER_ADDRESS` before a real `live-smoke-test` submit.

The readiness, metrics, README, and tests were updated so the funder/proxy rule
is explicit.

## Geoblock Rule

Do not bypass geoblock protection.

Every live order path must use the official endpoint:

```text
GET https://polymarket.com/api/geoblock
```

If the endpoint returns `blocked=true`, or if the endpoint cannot be verified,
live order placement must fail closed.

## One-Dollar Smoke Test Rule

The smoke test is only a connectivity test:

- dry-run is the default;
- one real order attempt maximum;
- FAK or FOK only;
- no loops;
- no automatic retries;
- no strategy logic;
- no market making;
- no automatic size increase;
- max real BUY notional remains 1 USDC.

For BUY smoke tests, `--max-notional` is the dollar amount sent to the market
order path. CLOB `min_order_size` is recorded in the report, but the test does
not automatically increase the order size. If the SDK or exchange rejects a
tiny FOK/FAK order, the report records the rejection.

## Diagnostics

Before a real smoke test, run:

```powershell
python -m pm_trader.cli live-account-status --redact-secrets
```

Expected safe fields:

- `signer_configured: true`
- `funder_configured: true`
- `active_wallet_source: funder`
- `balance_readable: true`
- `approval_readable: true`
- `positive_approval_count` greater than zero
- `open_order_count` checked
- `position_count` checked

No raw secret, private key, wallet address, or funder address should appear.

## Dry-Run Command

```powershell
python -m pm_trader.cli live-smoke-test `
  --auto-btc-5m `
  --outcome YES `
  --side BUY `
  --max-notional 1.00 `
  --order-type FAK `
  --dry-run
```

Expected result: `final_result=PASS`, `order_submitted=false`.

## Real Smoke Command

Run this only after diagnostics and dry-run pass:

```powershell
$env:TRADING_MODE="LIVE"
$env:LIVE_TRADING_ENABLED="true"

python -m pm_trader.cli live-smoke-test `
  --auto-btc-5m `
  --outcome YES `
  --side BUY `
  --max-notional 1.00 `
  --order-type FOK `
  --no-dry-run `
  --require-clean-git `
  --i-understand-this-places-a-real-order
```

## Verified Result

On July 1, 2026, the real smoke path was verified with a BTC Up/Down 5m market.

Observed safe summary:

- CLI result: `final_result=PASS`
- visible account order: BUY Up, about 1 USDC notional
- displayed fill: 1.3 shares at about 75c
- open-order risk: FOK order type, no intentional residual order loop

A second immediate FOK run was rejected by the SDK/exchange as the market moved.
That is acceptable and expected for a FOK smoke command; it does not mean the
connection fix failed.

## If This Breaks Again

Check these items first:

1. Confirm `POLYMARKET_PRIVATE_KEY` is the login EOA private key.
2. Confirm `POLYMARKET_FUNDER_ADDRESS` is the Polymarket trading proxy wallet,
   not the login EOA address.
3. Run `live-account-status --redact-secrets` and verify the active wallet
   source is `funder`.
4. Confirm balance and approval are readable and approval count is positive.
5. Confirm geoblock returns `blocked=false`.
6. Run dry-run first and inspect `live_smoke_test.json`.
7. Only then run the real FOK/FAK command once.

