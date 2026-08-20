# Release Handoff

This project uses local, sanitized release handoff artifacts. Do not publish
packages or submit live orders from this checklist.

## Required Commands

```powershell
python -m polysia.cli ops final-handoff --require-clean-git
```

## Expected Result

- Unit tests pass.
- Lint and type checks pass.
- Deployment readiness is `ready`.
- Release manifest is `ready`.
- `release-artifacts/release-manifest.json` is generated.
- `release-artifacts/operator-runbook.md` is generated.
- `release-artifacts/deployment-automation.json` is generated.
- `release-artifacts/final-handoff.md` is generated.
- Generated artifacts do not contain secrets, wallet addresses, token values, or
  transaction hashes.

## Stop Conditions

- The git worktree is dirty during strict handoff.
- Readiness or release manifest is blocked.
- Any output contains secret values or wallet addresses.
- A live command would move beyond dry-run.
