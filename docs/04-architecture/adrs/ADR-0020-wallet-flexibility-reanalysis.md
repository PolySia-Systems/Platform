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

## Consequences

Legacy top-three Runs remain readable with the original policy name and digest
inputs. Rollback is revert of this ADR, the Spec `wallet_count` field, and the
reanalysis command. Operational validation of counts other than three remains
outstanding.
