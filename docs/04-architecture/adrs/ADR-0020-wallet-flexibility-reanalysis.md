# ADR-0020: Configurable Polycop Wallet Count and Immutable Reanalysis

- Status: Accepted
- Date: 2026-09-20

## Context

PR 2 froze a versioned Spec/Plan with a three-wallet Polycop default. Operators
need a bounded way to request a different `SHADOW_ALPHA` count without editing
source, and a way to reanalyze captured evidence without rewriting the Bundle.

## Decision

CURRENT: `research-run-spec-v1` accepts optional `wallet_count`. Omitted or
explicit `3` keeps `polycop-shadow-alpha-top3-v1` and the validated Canary/Main
meaning. Counts `1` or `2` resolve to `polycop-shadow-alpha-configured-v1`.
Counts above the declared operational bound of `3` fail closed. Selection still
uses only distinct `SHADOW_ALPHA` ranks; `SHADOW_STRESS` is not a profitability
candidate. Resume uses the frozen reconstruction. Requested counts other than
three are labeled `unverified` capacity, not operationally supported.

CURRENT: A frozen Polycop Plan opens sources only through a factory that
declares named `wallet_count` and `selection_policy` parameters. Compatibility
is determined from `inspect.signature` before any call. An incompatible factory
fails closed without being invoked. A construction `TypeError` is not caught
and is not retried as a no-argument default top-three selection.

CURRENT: `research prospective-reanalyze` writes an additive analysis directory
with a separate result identity, provenance, analysis code SHA, and claim class.
It stages the complete result beside the destination, verifies protected source
evidence again, and atomically publishes the directory. A failed publication
leaves no final partial identity and the same analysis id is retryable. The
source Bundle and evidence hashes are verified unchanged. Analysis code identity
is an exact lowercase 40-character Git SHA. Post-hoc analysis is `EXPLORATORY`.
`CONFIRMATORY` requires a frozen hypothesis id, digest, and independent evidence
hash. New Runner Bundles record only the public frozen wallet-selection policy,
count, and digest; addresses are excluded. Legacy evidence without those fields
reports selection identity as `UNKNOWN`. Comparison reports wallet selection,
capture range, budgets, analysis version, evidence quality, and Control/Target
deltas, and does not infer causation.

CURRENT: detailed replay and Bundle manifests include a deterministic
single-wallet economic breakdown for each sanitized alias observed in valid
evidence. Each row is replayed independently from the same causal market
snapshots, rather than attributing a shared portfolio P&L after the fact.
Selected wallets with no accepted evidence remain absent from the breakdown;
the public frozen selection count makes the shortfall visible without exposing
addresses.

CURRENT: new Canary/Main Specs may explicitly request
`polycop-shadow-alpha-active-top3-v1`. This policy remains bounded to three
wallets and to the existing fresh `SHADOW_ALPHA` snapshot. Before T0 it measures
a fixed four-hour count of public Data API v2 trades for at most the top 50
distinct alpha candidates and freezes the three most active; deterministic
ties use alpha rank and wallet id. Activity is an observability gate, not an
economic score. The measurement window, sanitized counts, source, and digest
are preserved in run evidence. Source failure or fewer than three active
candidates fails closed. Existing runs and the default top-three policy are
unchanged.

## Consequences

Legacy top-three Runs remain readable with the original policy name and digest
inputs. Prospective public wallet collection uses the official Data API v2
envelope while retaining stable internal source ids. Rollback is revert of this
ADR, the optional Spec selection policy, the Spec `wallet_count` field, and the
reanalysis command. Operational validation of counts other than three remains
outstanding.

## Additive decision: measured capacity and pre-T0 choice (2026-09-28)

CURRENT: `research-run-spec-v3` and the separate
`continuous-shadow-runtime-v2` select 1–40 wallets in software. They use
one `wallet-capacity-v1` admission contract, with legacy three-wallet
behavior preserved under prior policy/version names. Operational permission
depends on a reviewed measurement record bound to code SHA and a digest of
profile, cadence, page/request/time budgets, source mode, selection policy,
and Shadow financial/period workload. The record is
operator supplied: its digest catches accidental changes but is not
authentication or independent proof of server capacity. The bounded probe
returns `CANDIDATE_ONLY`; it cannot mint a PASS record. Host-wide request
load, queue/recovery headroom, books/fees, CPU/memory, and storage must be
reviewed with actual Helsinki evidence before relying on a count above the
previous operational baseline. No official fixed wallet ceiling or invented
Data API numeric quota is assumed; the [current official v2 contract](https://data-api.polymarket.com/v2/docs) uses
`429`/Retry-After for client/serving pressure and `503`/Retry-After for
timeouts.

CURRENT: the new active policy shares deterministic selection logic between
Research and Shadow. It freezes complete four-hour preflight activity and
current market evidence before T0. Ranked and active are explicit policy
choices. Alternative 5/10/20/40 cohort rates compare observed data
availability only; selecting a cohort for formal evaluation starts a new
identified period. Neither candidate activity nor a short positive P&L is a
profitability score.

CURRENT: v3 Research status can opt into a read-only provisional sample
replay. It does not modify the 20/0.95/0.90 acceptance thresholds, shorten
frozen evaluation horizons automatically, or change old Bundles. Durable
finalization and replay remain required. A future adaptive-stop design would
need its own frozen statistical and valuation contract.
