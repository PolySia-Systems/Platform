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

## Cancellation finality boundary

Tiny Live Copy run four proved that a single immediate authenticated
open-order read may not confirm a just-requested cancellation even when later
reads show no open order or fill. The runtime correctly stopped `FAILED_SAFE`.
The CURRENT repair retains that historical evidence and replaces the unsafe
single-read conclusion with a venue-neutral execution gate. The adapter maps
fully paginated open orders, explicit 404-versus-error detail, order-linked
trades, positions, and cancellation acknowledgements into canonical contracts.
SDK models do not cross this boundary.

Before the external mutation, the gate persists a marker that means the send
may have occurred. It sends at most once, never automatically resends after a
restart, and performs only bounded reads afterward. `CONFIRMED_NO_FILL`
requires at least two consecutive complete observations; delayed/full/partial
fills, persistent open state, `not_canceled`, malformed evidence, endpoint
failure, timeout, and contradiction remain explicit terminal or fail-safe
outcomes. The sanitized
[fourth-run diagnostic](../18-ai-handoffs/polysia-tiny-live-copy-004-cancellation-diagnostic.md)
remains historical evidence and was not retroactively modified.

## SDK contract

The approved pinned baseline is the official unified
`polymarket-client==0.6.0`. Contract tests assert the installed version, the
SDK methods used by the public, secure, streaming, and reconciliation
boundaries, signer/private-key and funder/wallet creation inputs, and the
`condition_id` compatibility surface introduced before the stable 0.x
releases. SDK objects remain confined to the adapter boundary.

Contract fixtures also parse a representative official `OpenOrder` payload and
a mixed `CancelOrdersResponse`. Only a verified HTTP 404 maps to not found;
unexpected or malformed order-detail responses retain actionable sanitized
error context.

Any future upgrade requires a focused contract, lock, security, CI, and
rollback change. To restore 0.2.0, revert the 0.6.0 migration as one unit and
revalidate both portable locks. Current `main` supports only Python 3.14.
Restoring the historical Python 3.13.14 and SDK 0.1.0b11 baseline requires
reverting the associated compatibility and SDK decisions without changing
private credential values.
