# Copy Signal Arbiter Experiment Requirements

- **Status:** EXPERIMENTAL; not connected to the Live execution path
- **Scope:** generic Copy Trading selection, chronological Replay, and isolated Shadow
- **Out of scope:** Bitcoin five-minute support, Live activation, deployment, and changes to existing risk limits

## Verified Current Behavior

The CURRENT Tiny Live Copy path already deduplicates discovered events, reserves
signal capacity atomically, and permits at most one Entry Attempt per protected
leader in a run. The experiment must not weaken those controls. Its purpose is
to compare a future soft concentration policy with that verified baseline, not
to claim that repeat-leader selection is already active in production.

## Invariants

- The Risk Engine retains final authority.
- The ten-second signal-age limit, financial caps, rate limits, geoblock,
  circuit, kill-switch, reconciliation, and one-active-order-or-position rules
  remain unchanged.
- The Arbiter is synchronous and pure. It compares only candidates already
  available in one decision-time snapshot and never waits for more signals.
- A decision names at most one winner. The existing atomic reservation remains
  the authority that may admit that winner to an Entry Attempt.
- Rejected or losing candidates do not consume an Entry Attempt.
- Only protected internal leader keys may cross this boundary. Wallet addresses
  are rejected and must never be persisted or reported.

## Decision Order

```text
Safety
-> Freshness
-> Executable Net Edge
-> Wallet Score with Confidence
-> Concentration/Diversity Penalty
-> Deterministic Tie-break
```

Diversity applies only inside the configured near-equal executable-edge band.
The deterministic final tie-break is lower concentration penalty, fresher
signal, protected leader key, then protected signal key.

## Decision-Time Execution Evidence

The frozen post-only comparison defines:

```text
reference_cost = leader_fill_price * quantity
all_in_follower_cost = post_only_limit_price * quantity
                       + expected_fees
                       + estimated_slippage
executable_net_edge = reference_cost - all_in_follower_cost
```

The contemporaneous best bid and ask are required to validate the spread and
post-only price. Spread cost is reported separately because the observed quote
already determines the proposed limit price; it is not subtracted twice.
Missing, future, stale, inconsistent, or invalid decision-time price, spread,
fee, slippage, quantity, or timestamp evidence produces `UNKNOWN` and fails
closed. The experimental defaults require evidence no older than five seconds
and treat executable edges within `0.01` account-currency units as near-equal.

## Wallet and Follower Measurements

`Wallet Quality` uses every valid signal outcome whose evaluation horizon had
closed before the decision, including outcomes from signals the follower did
not select. `Follower Execution Quality` contains only the follower's own Fill,
cost, slippage, and net P&L evidence. The two datasets remain independent.

Wallet quality is an exponentially time-decayed empirical-Bayes estimate with
a neutral zero-return prior. The conservative selection score is:

```text
posterior_mean - uncertainty_multiplier * uncertainty * confidence
```

The prior weight keeps small samples close to neutral. Exact market type and
timeframe outcomes are preferred; the same leader's global history is used only
when no contextual outcome is available. At every Replay decision, only
outcomes with `closed_at <= decision_at` are visible.

The frozen scoring defaults are a prior weight of `20`, prior variance of
`0.01`, a 30-day evidence half-life, a one-sided `1.645` uncertainty multiplier,
and a `0.01` wallet-score near-tie band.

For future complete Bitcoin 15-minute datasets, outcome-labeling version
`executable-net-return-v1` means: take every valid OPEN BUY signal, use only the
decision-time all-in executable entry evidence, value the position at the first
executable bid at or after 900 seconds (or verified market resolution if it
occurs first), subtract entry and exit fees and modeled slippage, and divide the
net P&L by the all-in entry debit. Maximum drawdown uses only chronological
executable bids inside the same horizon. If any required quote or cost is
missing, the signal has no valid closed label and remains `UNKNOWN`. The legacy
historical Replay uses `legacy-no-outcomes-v1`, which explicitly freezes that no
outcome labels are available and cannot support a performance claim.

## Cause-Aware Concentration

- A rejected signal creates no concentration event.
- A market-caused or technical unfilled order creates no leader penalty.
- Repeated leader-attributable late signals may create a short penalty.
- Only a successful, fully closed follower cycle advances the adaptive
  30-, 60-, then 120-minute level.
- Idle 24-hour periods reduce the level, including between completed cycles, so
  an old history cannot permanently pin a leader at the maximum level.
- Concentration is a soft tie-break penalty, never a bypass of safety or
  executable quality.

The experimental late-signal default is two attributable late signals inside
30 minutes followed by a ten-minute soft penalty. Each full 24-hour idle period
reduces one completed-cycle level.

## Replay Contract and Conclusion Gate

The first Replay JSONL record freezes the schema version, outcome-labeling
version, evaluation horizon, and generation timestamp. Snapshots are ordered by
decision time and explicit snapshot key. The comparison modes are CURRENT,
COOLDOWN_ONLY, and FULL.

The report includes after-cost P&L, drawdown, latency, stale and unknown counts,
Fill quality, missed eligible signals, concentration, distinct leaders, and
confidence intervals. Result stability splits at least 30 chronological Fills
into three contiguous windows and requires every window's mean P&L direction to
agree with the overall direction. `BETTER` requires at least 30 complete
comparable Fills, non-overlapping conservative performance intervals, no worse
drawdown, no worse concentration, and consistent CURRENT and FULL windows.
Missing evidence or an unmet sample gate yields `INCONCLUSIVE`; the experiment
never invents values.

## Activation and Rollback

The experiment is additive and disabled in Live. Activation requires a later,
owner-authorized change that explicitly integrates the winner with the existing
atomic reservation and revalidates every runtime safety control. Before such an
activation, rollback is simply removal of the experimental modules and their
unused additive tables; no Live behavior or state migration depends on them.
