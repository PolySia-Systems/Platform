# Final Handoff

Use this command for the final local project handoff:

```powershell
python -m pm_trader.cli final-handoff --require-clean-git
```

The command runs the deployment automation, generates the release manifest,
generates the operator runbook, and writes `release-artifacts/final-handoff.md`.

## Expected Result

- Final handoff status is `ready`.
- Quality gates pass.
- Deployment readiness is `ready`.
- Release manifest is `ready`.
- Git worktree is clean.
- Generated artifacts remain under `release-artifacts/`.

## Generated Artifacts

- `release-artifacts/deployment-automation.json`
- `release-artifacts/release-manifest.json`
- `release-artifacts/operator-runbook.md`
- `release-artifacts/final-handoff.md`

## Safety Baseline

- Default runtime mode remains `DATA_ONLY`.
- Live trading remains disabled by default.
- Live submit and cancel paths remain protected by explicit acknowledgement flags.
- Generated handoff files must not contain secrets, wallet addresses, token
  values, or transaction hashes.
