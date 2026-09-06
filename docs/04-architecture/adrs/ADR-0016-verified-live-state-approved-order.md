# ADR-0016: Verified Live State and Exact Approved Market Requests

- Status: Accepted
- Date: 2026-09-06

## Context

Live risk fields defaulted to numeric zero, so unknown account state could
authorize an order. LiveBroker could submit market `shares`/`amount` values
that were not the Risk-approved size. Generic CLI limit-order accepted
operator-provided Position/P&L as if they were observed Live facts.

## Decision

UNKNOWN is not ZERO. ASSUMED is not VERIFIED. Live submission requires an
immutable `VerifiedLiveRiskSnapshot` evidence carrier built from authenticated
read-only Venue reads. Preview and Paper values are classified as assumptions
and cannot authorize Live submission. The generic live limit-order command is
preview-only.

Raw intent plus execution constraints are canonicalized into a side-aware
market request before Risk. BUY uses amount/max_spend and max_price. SELL uses
shares and min_price. Risk evaluates that exact maximum economic exposure and
freezes an `ApprovedOrder`. Execution and the Adapter may submit only that
request. A mismatch is rejected before any mutating Adapter call.

This is not an OMS, account-state service, or new database.

## Consequences

Tiny Live paths that cannot observe a required value remain blocked. Read-only
Adapter calls used to refresh verified state are allowed. Claim, freshness,
one-attempt, geoblock, and post-submit reconciliation remain independent
safeguards. DATA_ONLY and Live-disabled defaults are unchanged.
