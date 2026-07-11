# PolySia Project Charter

## Identity and purpose

PolySia is a professional, reality-first platform for prediction and event
markets. Polymarket is the first venue adapter and the existing Python system is
the implementation foundation. The near-term objective is to preserve and
professionalize the working Polymarket vertical slice; the long-term objective
is a venue-neutral platform that can add markets, brokers, wallets, chains, and
protocols without rewriting the core.

## Current scope

- Public and authenticated Polymarket connectivity.
- Market data, normalization, order books, strategies, risk, paper execution,
  positions, P&L, reconciliation, observability, and guarded tiny-live tooling.
- Modular-monolith boundaries, reproducible packaging, layered tests, and
  operator documentation.
- A canonical `polysia` distribution, import namespace, and CLI.

## Non-goals for this modernization

- Microservices or Kubernetes.
- Machine learning or unrestricted online learning.
- Production credential activation, capital scaling, or live strategy
  automation.
- New venue, Web3, DeFi, or copy-trading execution before the first adapter and
  core boundaries are stable.
- Claims of profitability or production readiness without evidence.

## First evidence-oriented vertical slice

`Public Polymarket event -> canonical market data -> strategy intent ->
independent risk -> paper execution -> position/P&L -> reconciliation ->
operator report`

It must be deterministic in tests, observable, credential-free, and incapable
of live mutation. The existing implementation already approximates this slice;
modernization will preserve it while removing venue coupling from the core.

## Success criteria

- All preserved baseline capabilities pass regression tests.
- Canonical identity is `polysia` with no internal legacy imports or command.
- Domain/application code does not import Polymarket SDK or adapter models.
- Dependencies and build are reproducible.
- Live mutation remains gated and excluded from ordinary CI.
- Architecture, risks, operations, migration, and rollback are documented.

