# Phase 32 Release Freeze and Production Gap Audit

Phase 32 adds a read-only release-management audit. It classifies the project
capabilities, documents what is safe now, what must remain dry-run only, and
what is blocked from live production.

Run:

```powershell
python -m pm_trader.cli production-gap-audit --output-dir .\release-artifacts
```

Generated artifacts:

- `release-artifacts/production-gap-audit.json`
- `release-artifacts/production-gap-audit.md`
- `release-artifacts/phase-31-freeze-summary.md`

The audit classifies capabilities as:

- `production-ready`
- `MVP-ready`
- `research-only`
- `paper-only`
- `blocked-for-live`
- `requires-human-review`

Release freeze rules:

- Live market making is not approved.
- Live strategy automation is not approved.
- Capital scaling is not approved.
- Repeated live tests are not approved.
- A second real tiny live test requires separate manual approval.
- Any production live trading requires a new phase and explicit operator
  approval.

Merge recommendation:

- Recommended tag: `v0.31.0-controlled-second-tiny-live-ready`
- Recommended merge target: `main`

Safety:

- Read-only only.
- No live broker submit.
- No live broker cancel.
- No retry loop.
- No live strategy automation.
- No live market making.
- Reports do not include private keys, wallet addresses, token IDs, transaction
  hashes, signed payloads, API credentials, or raw secrets.
