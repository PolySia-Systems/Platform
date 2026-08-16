# Module Decomposition

Phase F applies incremental extraction to the working implementation. Public
module imports and CLI command behavior remain compatible while command-neutral
logic, models, and renderers gain explicit homes.

## Completed split

| Original module | Before | After | Extracted boundary |
|---|---:|---:|---|
| `polysia.cli` | 2,866 lines | 2,582 lines | parsing, safe output, runtime credential bridging, and research helpers under `polysia.cli_support` |
| `monitoring.acceptance_audit` | 926 lines | 676 lines | acceptance data models and JSON/Markdown/HTML renderers |
| `execution.manual_intervention_live_test` | 909 lines | 848 lines | JSON/Markdown renderers |

The persistence boundary was already separate under `polysia.storage`; Phase F
does not rewrite it. Compatibility re-exports preserve established imports from
the original acceptance and manual-intervention modules. Private CLI helper
aliases used by tests and internal callers remain available where verified.

## Characterization and boundaries

- The Phase F Typer inventory was locked at 35 command names. The current
  inventory contains 41 top-level command or command-group names after later
  approved capabilities, including one `control` group bounded to `plan`,
  `apply`, `status`, and `history`.
- Existing CLI, acceptance-renderer, and manual-intervention tests remain the
  primary behavioral characterization suite.
- Architecture tests prevent renderer implementations from returning to the
  service modules and prevent Typer command wiring from entering CLI support.

The earlier Phase A/Phase C references to 34 commands are a historical counting
error: the Phase A Git snapshot itself contains 35 `@app.command` registrations.
No command was added or removed by this decomposition.

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

The main CLI still contains the Typer command functions and is intentionally
large. Splitting command groups further requires converting tests that monkeypatch
module globals into explicit dependency injection. Oversized monitoring and live
execution services should continue to move models, persistence, and rendering to
focused modules when each area is next changed; this is tracked debt, not a reason
to perform a high-risk rewrite during migration.
