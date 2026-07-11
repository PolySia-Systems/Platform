# Phase F Module Decomposition Handoff

Implementation commit: `c3049b23ace4749654bb3422f0fc00889cad10af`

## Outcome

The large CLI and representative oversized monitoring/execution modules now
have explicit support, model, and renderer boundaries. The established imports
remain compatible through re-exports, and command-neutral CLI helpers are no
longer implemented inside Typer command wiring.

The Phase A snapshot contains 35 command registrations. Earlier references to
34 were a counting error; characterization now locks the exact 35-name command
inventory and proves that this phase added or removed no command.

## Verification

- Compile: passed.
- Secret scan: passed.
- Ruff: passed.
- Mypy: passed for 105 source files.
- Pytest: full suite passed; 351 tests collected.
- Focused CLI/acceptance/manual-intervention characterization: 73 passed.
- `pip check`: passed.
- Pre-commit aggregate gate: passed.
- Live/authenticated state mutation: not executed.
- Credential values: unchanged and not exposed.

## Decomposition evidence

- `polysia.cli`: 2,866 to 2,582 physical lines.
- `monitoring.acceptance_audit`: 926 to 676 physical lines.
- `execution.manual_intervention_live_test`: 909 to 848 physical lines.
- New focused modules: four CLI support modules, acceptance models/renderers,
  and manual-intervention renderers.

Further command-group dependency injection and incremental extraction from
other oversized services remain registered technical debt; a broad rewrite was
not required to meet this phase's safe split and would add migration risk.

## Rollback

Revert the implementation commit. The compatibility tests, earlier phase
commits, external backup, legacy folder, and old Conda environment remain
available.

## Next action

Proceed to Phase H in strict order: authenticated read-only checks, paper, then
shadow validation. Do not perform a state-changing live-network test without
explicit owner authorization for that specific run.
