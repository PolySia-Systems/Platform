# Module Decomposition

The repository applies incremental extraction to the working implementation.
Public CLI behavior remains compatible while command ownership, command-neutral
support, models, and renderers gain explicit homes.

## Completed split

| Original module | Before | After | Extracted boundary |
|---|---:|---:|---|
| `polysia.cli` | 2,876 lines | 63 lines | flat Typer composition in `cli.py`; command ownership under `polysia.cli_commands`; neutral support under `polysia.cli_support` |
| `monitoring.acceptance_audit` | 926 lines | 676 lines | acceptance data models and JSON/Markdown/HTML renderers |
| `execution.manual_intervention_live_test` | 909 lines | 848 lines | JSON/Markdown renderers |

The persistence boundary remains separate under `polysia.storage`; this work
does not rewrite it. Compatibility re-exports preserve established imports from
the original acceptance and manual-intervention modules. CLI command modules use
module-qualified `cli_support` functions, so the composition facade no longer
needs private helper aliases.

## Characterization and boundaries

- The Phase F Typer inventory was locked at 35 command names. The current
  inventory contains 41 top-level command or command-group names after later
  approved capabilities, including one `control` group bounded to `plan`,
  `apply`, `status`, and `history`.
- Existing CLI, acceptance-renderer, and manual-intervention tests remain the
  primary behavioral characterization suite. CLI unit tests mirror `core`,
  `research`, `operations`, and `live` command ownership, with safety defaults
  retained as an independent concern.
- Architecture tests prevent renderer implementations from returning to the
  service modules, prevent Typer command wiring from entering CLI support, and
  keep `polysia.cli` as one-way composition over the command modules.

The earlier Phase A/Phase C references to 34 commands are a historical counting
error: the Phase A Git snapshot itself contains 35 `@app.command` registrations.
The earlier support extraction reduced `polysia.cli` from 2,866 to 2,582 lines;
later approved capabilities increased it to 2,876 lines before the structural
decomposition. No command was added, removed, renamed, hidden, or regrouped by
the current decomposition.

## Shadow Control Kernel boundary

The first Control Kernel slice keeps typed immutable models, planning,
validation, policy, idempotency, and reconciliation under `polysia.control`.
Typer wiring is isolated in `polysia.control.cli`; SQLite serialization remains
an outer adapter in `polysia.storage.control`. The existing deterministic
`monitoring.shadow_run` loop accepts a narrow injected intent boundary directly
before `BaseStrategy.on_market_event`.

The boundary supports only `stale-price@0.1.0` in `SHADOW`. It is not a daemon,
strategy orchestrator, Live controller, or replacement for the Strategy
Registry. Architecture tests keep the control core venue-neutral and free of
SQLite adapter imports.

## Remaining incremental debt

The root CLI is now composition-only. The `operations` and `live` command
modules still contain broad orchestration and some module-global seams used by
tests. Future focused changes may move that orchestration behind explicit
services and dependency injection without changing the flat command surface.
Oversized monitoring and live execution services should likewise continue to
move models, persistence, and rendering to focused modules when each area is
next changed; this is tracked debt, not a reason for a high-risk rewrite.
