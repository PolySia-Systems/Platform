# Polymarket Adapter

## Boundary

All official Polymarket SDK imports remain confined to
`src/polysia/adapters/polymarket/`. Important current responsibilities include:

- public market/order-book reads and server-time access;
- authenticated account, order, trade, balance, and position reads;
- guarded execution/cancellation primitives used behind existing safety gates;
- streaming and normalization;
- fail-closed geoblock checks;
- SDK-to-domain mapping and capability description;
- sanitized structured error classification;
- read-only round-trip reconciliation and lifecycle health reads.

Domain, application, strategy, risk, portfolio, ledger, and persistence
contracts consume canonical models rather than SDK response objects.

## Current guarded behavior

The adapter supports public streaming, authenticated reads, limit/market
operations, cancellation, FAK/FOK, and post-only workflows. The bounded
round-trip path uses one minimum-valid FAK entry and one actual-fill-sized GTC
exit. It does not automatically retry, replace, or resubmit a mutation.

Official CLOB server time is used for an authenticated preflight that fails
closed on timeout, missing time, malformed time, or excessive positive/negative
drift. Read-only transient failures may use bounded backoff. Geoblock and
trading-prohibition results remain terminal, not retryable transient errors.

Diagnostics retain sanitized status/error codes and safe venue messages while
classifying authentication, signature, amount/quantity, minimum/tick, funding,
order-type, market, geoblock, rate-limit, clock, SDK, server, timeout, and
unknown failures. Credentials, signatures, keys, tokens, and sensitive request
payloads are never included.

## SDK contract

The approved pinned baseline is the official unified
`polymarket-client==0.2.0`. Contract tests assert the installed version, the
SDK methods used by the public, secure, streaming, and reconciliation
boundaries, and the `condition_id` compatibility surface introduced before the
stable 0.x releases. SDK objects remain confined to the adapter boundary.

Any future upgrade requires a focused contract, lock, security, CI, and
rollback change. The currently verified rollback returns to the Python 3.13.14
and SDK 0.1.0b11 baseline without changing private credential values.
