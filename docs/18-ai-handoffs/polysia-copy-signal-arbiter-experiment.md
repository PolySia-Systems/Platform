# PolySia Copy Signal Arbiter Experimental Handoff

The experimental `FULL` policy is not a Live authority. Runtime exposure is
guarded by `POLYSIA_COPY_SIGNAL_ARBITER_FULL_ENABLED`, whose default is `false`.
If both Live trading and this flag are enabled, startup fails closed because
this release deliberately accepts no separate owner authorization for `FULL`.
Offline Replay and non-mutating evaluation remain available.

## Outcome

An isolated, generic Copy Trading Signal Arbiter, additive evidence persistence,
and chronological Replay comparison were implemented on a separate branch.
They are EXPERIMENTAL and are not connected to Tiny Live Copy execution.

The verified CURRENT runtime already prevents repeat use of one protected
leader within a run. This delivery preserves that safer behavior and provides
an evidence-based comparison path for a possible future soft concentration
policy.

## Implemented Design

The pure selector applies Safety, the unchanged ten-second freshness gate,
complete decision-time execution evidence, near-equal executable edge,
confidence-aware wallet quality, cause-aware concentration, freshness, and a
protected deterministic identifier. It does not wait, perform I/O, reserve
capacity, or mutate an account.

Wallet Quality is walk-forward, contextual, empirical-Bayes, time-decayed, and
learned from all closed valid signal outcomes. Follower Execution Quality is
stored and reported separately. Missing evidence is `UNKNOWN` and fails closed.
Only a fully closed successful follower cycle can create the adaptive
30/60/120-minute concentration event.

The detailed frozen contract is in
[`copy-signal-arbiter-experiment.md`](../03-requirements/copy-signal-arbiter-experiment.md).

## Historical Replay Evidence

The protected prior-run input was read from the server without changing server
state and copied only into ignored local artifacts. The bounded wallet-address
scan found no protected address in the sanitized input or generated output.

The prior report contained 170 sanitized events: 33 `OPEN` and 137 `INCREASE`.
The 33 OPEN records formed 20 decision-time snapshots. Twenty-eight records
were already beyond the unchanged ten-second freshness limit. The remaining
five lacked the decision-time order book, proposed executable price, quantity,
fees, slippage, and closed follower outcomes. The historical order-book report
was empty. Therefore all three modes correctly selected zero signals and the
comparison returned `INCONCLUSIVE` rather than inventing data.

| Mode | Snapshots | Selected | Stale | Unknown evidence | Known Fills |
| --- | ---: | ---: | ---: | ---: | ---: |
| CURRENT | 20 | 0 | 28 | 5 | 0 |
| COOLDOWN_ONLY | 20 | 0 | 28 | 5 | 0 |
| FULL | 20 | 0 | 28 | 5 | 0 |

## Validation

Focused implementation regressions and the existing atomic reservation,
deduplication, restart recovery, and rate-limit regressions passed. The final
local repository gates passed:

- compileall and `git diff --check`
- Ruff
- Mypy across 131 source files
- Pytest: 617 passed
- `pip check`
- repository secret scan
- source distribution and wheel build
- strict OSV dependency audit: no known vulnerabilities
- CycloneDX environment SBOM generation

Draft PR and hosted CI evidence are recorded in the PR and final completion
report after they finish; they must not be inferred from this local handoff.

## Live and Shadow Status

No Live process, deployment, runtime setting, account, scheduler, or database
was changed. No new Live run was started. Shadow is deferred unless a runtime,
database, scheduler, and request budget fully isolated from the active Live run
can be proven. The experimental branch has not been deployed, so server Shadow
must not be implied.

## Future Activation Gate

Any Live integration needs a separate owner-approved change, Authorization ID,
and Run ID. It must route only the single Arbiter winner through the existing
atomic reservation, risk, execution, and reconciliation path, and must repeat
the relevant safety, regression, Shadow, CI, deployment, and commit-identity
checks.
