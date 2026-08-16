# Shadow Control Kernel Operations

## Scope

The first Control Kernel slice controls only `stale-price@0.1.0` in `SHADOW`.
It cannot enable PAPER or LIVE, change strategy parameters, contact a venue, or
replace Risk, reconciliation, monitoring, or emergency controls.

`RUNNING` permits new Shadow strategy intents. `PAUSED` suppresses only new
strategy intents; it is not shutdown, cancel-all, position closure, or Kill
Switch activation.

## Plan and apply

Use one shared SQLite path for every command. Planning is read/validation plus
an immutable plan record; it does not change desired state.

```powershell
polysia control plan PAUSED `
  --database-path data/polysia.sqlite3
```

Read `plan_id` and `expected_revision` from the JSON response, then apply the
exact plan with a unique non-secret command label:

```powershell
polysia control apply `
  --plan-id <plan-id> `
  --command-id pause-20260817-001 `
  --expected-revision 0 `
  --actor owner `
  --database-path data/polysia.sqlite3
```

If another command changed the revision first, apply fails and requires a new
plan. Repeating the identical command ID and payload returns the original result
without creating another revision. Reusing an ID with different content fails.

## Verify the real Shadow boundary

The deterministic Shadow CLI uses the persisted control database by default.
Pass the same explicit path when operating outside the default working directory:

```powershell
polysia shadow-run `
  --max-events 4 `
  --control-database-path data/polysia.sqlite3 `
  --json
```

A verified pause reports `SHADOW_PAUSED`, `operational_state=PAUSED`, the
acknowledged revision, and zero strategy intents, Risk decisions, paper orders,
and paper fills. A reconciliation error reports `UNKNOWN`/`FAILED`; writing
Desired State alone never produces a success claim.

## Status and history

```powershell
polysia control status --database-path data/polysia.sqlite3
polysia control history --database-path data/polysia.sqlite3
```

Status separates desired from observed state. History is append-only and
contains sanitized command, plan, policy, reconciliation, and revision evidence.
Actor labels are audit metadata and are not authentication.

## Resume

Create a new plan for `RUNNING` against the current revision and apply it with a
new command ID. Never edit or delete an older SQLite revision.

```powershell
polysia control plan RUNNING --database-path data/polysia.sqlite3
```

## Recovery and rollback

Before operational use, include the SQLite file in the existing verified backup
procedure. Restore follows the existing SQLite recovery runbook.

Configuration revert is intentionally not implemented. A future revert will
append a new forward revision based on an older desired state; it will not erase
history or undo external-world activity. Code rollback is a normal commit revert.
The additive control tables are inert when no Control Kernel command or opted-in
Shadow run uses them.
