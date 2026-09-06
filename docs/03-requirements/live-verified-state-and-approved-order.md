# Verified Live State and Exact Approved Orders

Status: CURRENT
Architecture status: CURRENT

Live submission is authorized only from verified account and market-data
evidence. Unknown, unavailable, stale, or assumed values cannot authorize an
order. Measured zero remains distinct from unknown.

## Evidence carrier

`VerifiedLiveRiskSnapshot` is an immutable evidence object, not an
account-state subsystem. It carries current token position, current market
position, daily realized cash effect from today's account trades, open-order
count, market-data observation time, account/source identity, and `observed_at`.
Freshness is calculated at decision time against `RiskLimits.max_stale_data_age_ms`.

Preview and Paper inputs are classified as `assumed`. The generic
`live limit-order` command is preview-only; operator-provided Position/P&L
values cannot authorize submission.

## Canonical market request

Transformations occur before Risk:

- BUY: `amount` or `max_spend` is spend exposure; `max_price` is price
  protection; SELL-style `shares` are forbidden.
- SELL: `shares` is quantity exposure; `min_price` is price protection;
  BUY-only `amount`/`max_spend` are forbidden.

Risk evaluates that maximum economic exposure and freezes `ApprovedOrder`.
LiveBroker submits exactly that request. Adapter side-specific validation is
defense in depth and does not move Risk authority into the Adapter.

## Failure and recovery

A blocked Live order makes zero mutating Adapter or order-submission calls.
Read-only collection and refresh remain allowed. Resume requires verified
state and an exact approved request; there is no automatic repair of assumed
or unknown Live inputs.

These rules do not change DATA_ONLY or `LIVE_TRADING_ENABLED=false` defaults.
