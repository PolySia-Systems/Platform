# POLYSIA-LIVE-004 Final Handoff

## Outcome

`POLYSIA-LIVE-004` completed the authorized execution validation as
`ENTRY_FILLED_EXIT_OPEN`. Exactly one live FAK entry was submitted, filled for
the venue minimum quantity, and followed by exactly one GTC take-profit sell
order sized to the reconciled position. The exit remained open at the final
reconciliation read.

## Implementation and validation

- Pull Request #18 changed only the bounded round-trip strategy, runner, and
  focused tests.
- Runtime merge commit: `95faa172ded9332df14cb6f287b41e78e7b2cd9f`.
- Local validation passed: compile, Ruff, Mypy over 113 source files, 422
  Pytest tests, `pip check`, secret scan, and source/wheel build.
- Pull Request #18 passed all six quality and supply-chain checks. Post-merge
  main CI run `29208216484` also passed.
- Existing Risk authority, geoblock, kill switch, synchronized-main, green-CI,
  allowlist, redaction, persistence, reconciliation, and persistent one-attempt
  controls remained active.

## Live evidence

- Authorized run ID: `23108979-2693-4bb4-8199-5c34acaaf39b`.
- Market: `btc-updown-15m-1783889100`, selected outcome `Down`.
- Venue minimum quantity: `5`; tick size: `0.01`.
- Current executable entry price: `0.52`; displayed selected ask liquidity:
  `124.4` shares.
- Intended entry notional: `2.60`; expected fee: `0.08736`; intended all-in
  cost and maximum spend: `2.68736`, below the `10.00` cap.
- Entry: one FAK submission, accepted and fully filled for `5` shares at a
  weighted-average price of `0.52`.
- Exit: one accepted GTC sell for the reconciled `5` shares. The raw 10% target
  `0.5720` was normalized upward to the valid tick price `0.58`.
- Final remaining position: `5` shares covered by the open exit order.
- Reconciliation: `ready`, `states_match`, one internal and one external open
  order, no warning, no manual intervention, and no safety pause.
- Sanitized JSON SHA-256:
  `DB7538F4CC2F123A915FDFB26AC2A49C979142C0BEA32E01132DB765A1A3BF73`.
- Ignored local evidence:
  `release-artifacts/tiny-live-round-trip/23108979-2693-4bb4-8199-5c34acaaf39b/`.

Earlier dry-run or submit-mode preflights stopped before the persistent claim
because of stale data, inactive live-mode settings, a transient geoblock read,
legacy one-dollar/one-share environment caps, or a transient public API read.
Every such run recorded zero live entry attempts. Per-process limits for the
successful run were narrowed to the authorized `10.00` notional cap and exact
`5`-share venue minimum; no tracked or persistent runtime configuration changed.

## Closure

The `POLYSIA-LIVE-004` authorization is consumed. No entry retry, replacement,
averaging down, second market, or second live submission is permitted. The
single GTC exit order is live external state and must not be duplicated.
