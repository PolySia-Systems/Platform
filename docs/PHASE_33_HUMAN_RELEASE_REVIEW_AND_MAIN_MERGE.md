# Phase 33 Human Release Review and Main Merge

Phase 33 adds a local release-owner review package for tag verification and a
controlled main merge. It is release-management-only and does not change trading
behavior.

Run:

```powershell
python -m pm_trader.cli main-merge-review --output-dir .\release-artifacts
```

Generated artifacts:

- `release-artifacts/main-merge-review.json`
- `release-artifacts/main-merge-review.md`
- `release-artifacts/tag-and-merge-checklist.md`

The package includes:

- current branch, commit, and clean git status
- local tag status for `v0.31.0-controlled-second-tiny-live-ready`
- remote status, where a missing remote is a warning only
- recommended merge target: `main`
- quality gate summary
- production gap audit status
- final handoff status
- deployment readiness status
- live safety baseline
- blocked-for-live and dry-run-only capabilities
- human approval, rollback, and post-merge verification checklists

Explicit non-approvals:

- This package does not approve live trading.
- This package does not approve a second real tiny live test.
- This package does not approve capital scaling.
- This package does not approve live market making.
- This package does not approve live strategy automation.
- Merge to main requires human release-owner approval.
- Remote push is not required for local release review.

Safety:

- No live order submit path.
- No live order cancel path.
- No live strategy automation.
- No retry loop.
- No live market making.
- No trading behavior changes.
- Reports do not include private keys, wallet addresses, token IDs, transaction
  hashes, signed payloads, API credentials, or raw secrets.
