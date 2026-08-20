# Accelerated Stabilization Final Handoff

## Objective and baseline

`POLYSIA-STAB-001` removed immediate repository/dependency uncertainty and
prepared one evidence-oriented implementation plan without changing runtime
behavior. Discovery began with local HEAD
`3572bfd163f8bbb9a4811e28e95a3c3ffb25b022`; verified `main` and `origin/main`
were both `0baa804e2a1407b47d019ca5430cc60da7e44277`. Two unrelated untracked
architecture prompt inputs were preserved unchanged.

## Merges and PR dispositions

- PR #8, project status: merged as
  `c81d79cde1c92c832c493564ef4cccf44e278a61`.
- PR #4, `actions/setup-python` 5 -> 6: merged as
  `530a9d2becaea4312ed831e1d5b289cd8d61fb3f` after updated-branch and
  post-merge CI passed.
- PR #6, `actions/checkout` 4 -> 7: merged as
  `efe3a185ea4705a968fd2d90bd3cb059c7aece1a` after updated-branch and
  post-merge CI passed.
- PR #2, `actions/upload-artifact` 4 -> 7: merged as
  `b641e14cdb371d8e3ae4e1d700ca4c76cf93d622` after updated-branch and
  post-merge CI passed.
- PR #3, Mypy 2.2.0: HOLD because the PR omits the matching pip lock update.
- PR #7, Ruff 0.15.21: HOLD because the PR omits the matching pip lock update.
- PR #5, Polymarket SDK b18: HOLD. It omits the lock update, fails the approved
  SDK-pin contract on Python 3.11/3.13 (350 passed, 1 failed), and lacks required
  adapter/signing/execution/cancellation/streaming/reconciliation compatibility
  evidence. No test or pin was weakened.

The dependency PRs were reviewed and, where approved, merged one at a time.
Hold reasons were posted on their Pull Requests.

## Validation evidence

- Current post-merge CI run `29158912577`: Python 3.11 quality passed, Python
  3.13 quality passed, strict OSV supply-chain job and SBOM upload passed.
- Local `PolySia`/Python 3.13.14: compile passed; Ruff passed; Mypy passed on 105
  files; Pytest passed 351/351; pip check passed; secret scan passed; source and
  wheel build passed.
- Conda lock matched 22 explicit packages. Pip lock matched 119 packages, with
  only the Conda-managed pip bootstrap URL intentionally excluded.
- CycloneDX output parsed as valid JSON with 121 components.
- Local strict OSV audit was attempted twice and received HTTP 403 from the OSV
  service. Current CI ran the same strict gate successfully, so this is recorded
  as a local external-service limitation, not a product failure.
- No formatter is configured. No flaky/skipped test or product warning was
  observed.

## Unresolved risks

- SDK b18 compatibility is not proven; keep `polymarket-client==0.1.0b11`.
- Mypy and Ruff updates need coordinated lock changes and reproducibility proof.
- Cross-platform hash locking and branch protection remain governance debt.
- Any live mutation remains prohibited without run-specific owner authorization.

## Active plan and exact next task

The active plan is `plans/active/first-evidence-sprint.md`.

Next task: implement that plan as a bounded public-data, paper-only evidence
runner for the existing `StalePriceStrategy` on BTC Up/Down 5-minute markets.
Preserve Strategy -> minimal portfolio admission record -> independent Risk ->
PaperBroker -> PositionLedger -> ReconciliationManager, then generate the
registered daily evidence report. Do not implement a generalized allocator,
new strategy, SDK upgrade, or live execution.

## Rollback

The three merged dependency changes are isolated workflow-line replacements and
can be reverted independently by their squash commits. Reverting
`b641e14cdb371d8e3ae4e1d700ca4c76cf93d622`,
`efe3a185ea4705a968fd2d90bd3cb059c7aece1a`, or
`530a9d2becaea4312ed831e1d5b289cd8d61fb3f` restores the preceding Action
version. No runtime dependency, schema, credential, or external account state
changed.

## Reviewer focus

- Confirm the evidence plan remains single-strategy, paper-only, and
  venue-neutral outside the adapter.
- Confirm the portfolio admission step is explicitly not the TARGET generalized
  allocator and never overrides Risk.
- Confirm fee, slippage, capital-lockup, resolution, reconciliation, sample, and
  stop rules fail closed and do not imply profitability.
- Confirm the two pre-existing untracked prompts remain untouched.
