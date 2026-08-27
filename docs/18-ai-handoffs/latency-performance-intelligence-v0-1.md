# Latency & Performance Intelligence v0.1

Status labels: **CURRENT** describes merged code and tests. **PENDING** describes
Helsinki real-data acceptance that requires 24 continuous healthy hours after
deploy. This document does not claim production performance improvement.

## Objective

Explain where time is spent from source observation through current Stage 4B
processing and simulated economic outcomes, using reproducible evidence, without
changing trading behavior, financial state, or Live authority.

## CURRENT implementation

- Versioned venue-neutral contract `performance_contract_version=1.0`.
- Optional fail-open recorder injected beside Continuous Shadow. Strategy, Risk,
  Submit, ACK, First Fill, Final Fill, Decode, Normalize, Pricing, Execution
  Preparation, and WebSocket RTT remain `UNKNOWN` until those stages exist.
- Additive SQLite telemetry tables (`latency_telemetry_schema` v1). Continuous
  Shadow remains schema v4. Telemetry never holds a transaction across
  financial work. Buffer overflow and SQLite busy drop measurements.
- Out-of-band probes use the existing Polymarket `VenueErrorCategory` taxonomy
  and sanitized endpoint IDs. Probes never run inside `collect_events`.
- Canonical object `latency_performance_intelligence` is computed once and
  rendered to JSON, Markdown, and the existing observability HTML. Renderers do
  not recalculate metrics.
- `source_to_observation_ms` is not labeled as network RTT.
- Docker-versus-Native tooling exists but the real comparison is `not_run`
  until the Helsinki baseline is trustworthy.

## Safety

- `TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`.
- No real order, cancel, or signing path.
- Telemetry failure cannot roll back financial state.
- Do not `compose run` the live `wallet-intelligence-shadow-portfolio` worker.

## PENDING after Finland deploy

Real-data answers remain `INSUFFICIENT_DATA` until at least 24 continuous
healthy Helsinki hours, metric-specific sample thresholds, no monitoring-induced
restart, and no SQLite/Ledger regression.

Resume verification with the worker health artifact plus
`reports/wallet-intelligence/latency-performance-intelligence.json` after that
window. Do not invent significance before the thresholds are met.
