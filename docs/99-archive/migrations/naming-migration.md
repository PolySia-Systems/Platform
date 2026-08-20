# PolySia Naming Migration

## Change

The canonical distribution, import namespace, and CLI are now `polysia`.
The previous distribution `polymarket-trading-system`, namespace `pm_trader`,
and command `pm-trader` are removed from the active implementation.

No compatibility shim was added because no external consumer was available or
identified during inventory. Archived documents keep their historical wording.

## Operator migration

```powershell
conda activate PolySia
python -m pip uninstall -y polymarket-trading-system
python -m pip install --no-deps -e .
polysia --help
python -m polysia.cli system health
```

Venue-specific variables retain their `POLYMARKET_` names. Current generic
runtime variables retain their existing names during this behavior-preserving
rename; any future `POLYSIA_` aliases require configuration migration tests.

## Verification

- `import polysia` succeeds.
- `import pm_trader` fails.
- `polysia --help` succeeds.
- `pm-trader` is absent from the PolySia environment.
- Package metadata names distribution `polysia` and entry point
  `polysia = polysia.cli:app`.
- Compile, lint, type, tests, dependency, build, and clean-wheel smoke checks
  pass.

## Rollback

Reset to commit `aec9dfa`, uninstall `polysia`, and reinstall that commit in the
unchanged `PolySia` environment. For full recovery, use the preserved
`Polymarket Python SDK` folder or the verified pre-migration archive documented
in the Phase A baseline audit. Rollback must not alter `.env` values.
