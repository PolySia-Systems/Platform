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

CURRENT: `research prospective-reanalyze` writes an additive analysis directory
with a separate result identity, provenance, analysis code SHA, and claim class.
The source Bundle and evidence hashes are verified unchanged. Post-hoc analysis
is `EXPLORATORY`. `CONFIRMATORY` requires a frozen hypothesis id, digest, and
independent evidence hash. Comparison reports wallet selection, capture range,
budgets, analysis version, evidence quality, and Control/Target deltas, and
does not infer causation.

## Consequences

Legacy top-three Runs remain readable with the original policy name and digest
inputs. Rollback is revert of this ADR, the Spec `wallet_count` field, and the
reanalysis command. Operational validation of counts other than three remains
outstanding.
