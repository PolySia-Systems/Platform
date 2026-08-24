# Dynamic Wallet-Intelligence Pre-Live Handoff

## Status and objective

- **Status:** CURRENT DATA_ONLY capability; no Live authority
- **Policy version:** `dynamic-live-handoff-v0.1`
- **Objective:** deterministically materialize a protected candidate bank from
  current Stage 3 and Stage 4 evidence for a later, separately authorized Tiny
  Live Copy dry-run.

This handoff removes the operational dependency on a manually maintained
102-address file. The exact count remains an invariant of the existing bounded
Tiny Live Copy experiment and is not generalized by this change. The existing
Live runner's BTC 15-minute market gate, Risk checks, Execution controls,
geoblock, kill switch, caps, reconciliation, and run-specific authorization are
unchanged.

## Inputs and eligibility

The handoff requires:

1. current Stage 3 `SHADOW_ALPHA` and `SHADOW_STRESS` membership;
2. a successful current Historical Dynamic Shadow run for the same Stage 3
   `selection_run_id`;
3. Historical evidence not older than eight days;
4. at least one event and one simulated event for each selected wallet;
5. zero rejected events and `unknown_count / event_count <= 0.50`.

Fewer than 102 qualified wallets is a terminal safe failure for that attempt.
No partial bank is published.

## Determinism and publication

Qualified wallets are ordered by Alpha membership, simulated-event count,
unknown ratio, modeled realized PnL, Alpha rank, Stress rank, and canonical
wallet id. The first 102 are validated through the existing protected
`CandidateBank` contract.

The address file and versioned manifest are mode `0600` under a mode `0700`
directory. The manifest contains counts, policy/cost versions, run ids, and
digests but no address. A digest collision fails safely. Publication creates a
hard link to the immutable versioned bank and atomically replaces only the
current link; failed work preserves the last-known-good input.

## Safety boundary

The Compose handoff service:

- forces `TRADING_MODE=DATA_ONLY` and `LIVE_TRADING_ENABLED=false`;
- clears the Live token allowlist;
- has no network;
- mounts the wallet-intelligence database read-only;
- imports no Strategy, Risk, Execution, wallet, signer, or venue adapter;
- cannot submit, cancel, transfer, or mutate an external account.

The output only makes the existing Tiny Live Copy **dry-run preflight** easy to
invoke. Real submission still requires a different explicit owner-authorized
run and all existing fail-closed gates. A generic all-market Live execution path
remains outside this requirement.

## Acceptance criteria

- Exactly 102 unique normalized addresses are published from current evidence.
- Repeated identical evidence is idempotent and produces the same digest.
- Insufficient, stale, mismatched, malformed, or conflicting evidence leaves the
  current bank unchanged.
- CLI output, logs, tests, and the manifest expose no raw address.
- Architecture and Compose tests prove the absence of Live authority.
