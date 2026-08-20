# CLI Capability Migration

## Decision

The canonical CLI is capability-oriented:

```text
polysia system ...
polysia market ...
polysia research ...
polysia ops ...
polysia control ...
polysia live ...
```

Forty former flat commands are consolidated into these namespaces. The
existing `control` group is kept unchanged. No command implementation is
retired because every callback retains unique behavior, a tracked consumer, or
an evidence/safety purpose that lacks a proven replacement.

The former flat names remain callable as hidden compatibility aliases. Each
alias invokes the same callback as its canonical replacement, so options,
arguments, defaults, output, exit behavior, and safety gates are shared rather
than reimplemented. The aliases are intentionally not marked with Click's
runtime deprecation flag because extra stderr output would disturb health
checks and automation.

## Alias expiry condition

Remove the hidden aliases only in an owner-approved breaking-change review
after all of the following are true:

1. PolySia has passed the `v0.2.0` milestone.
2. The controlled server has been updated and verified with namespaced Compose
   commands.
3. Every tracked script, CI job, runbook, and generated command uses the
   namespaced surface.
4. External-consumer impact has been reviewed and the removal has explicit
   rollback instructions.

This pull request updates tracked repository consumers but does not deploy or
change the controlled server. Therefore the compatibility aliases remain.

## Classification matrix

`Interaction` describes the maximum capability of the command, even when its
default path is dry-run. `CONSOLIDATE` changes only the canonical route and
retains the underlying callback.

| Former command | Role | Status | Interaction | Canonical replacement | Final decision |
|---|---|---|---|---|---|
| `health` | CORE | CURRENT | NONE | `system health` | CONSOLIDATE |
| `configuration-status` | CORE | CURRENT | NONE | `system configuration` | CONSOLIDATE |
| `operator-status` | OPERATIONS | CURRENT | NONE | `system status` | CONSOLIDATE |
| `operator-report` | OPERATIONS | CURRENT | LOCAL_STATE | `system report` | CONSOLIDATE |
| `deployment-readiness` | OPERATIONS | CURRENT | LOCAL_STATE | `ops deployment-readiness` | CONSOLIDATE |
| `operator-runbook` | OPERATIONS | CURRENT | LOCAL_STATE | `system runbook` | CONSOLIDATE |
| `release-manifest` | OPERATIONS | CURRENT | LOCAL_STATE | `ops release-manifest` | CONSOLIDATE |
| `deployment-automation` | OPERATIONS | CURRENT | LOCAL_STATE | `ops deployment-automation` | CONSOLIDATE |
| `final-handoff` | OPERATIONS | CURRENT | LOCAL_STATE | `ops final-handoff` | CONSOLIDATE |
| `acceptance-audit` | OPERATIONS | CURRENT | LOCAL_STATE | `ops acceptance-audit` | CONSOLIDATE |
| `production-gap-audit` | OPERATIONS | HISTORICAL | LOCAL_STATE | `ops production-gap-audit` | CONSOLIDATE |
| `main-merge-review` | OPERATIONS | HISTORICAL | LOCAL_STATE | `ops main-merge-review` | CONSOLIDATE |
| `local-release-closeout` | OPERATIONS | HISTORICAL | LOCAL_STATE | `ops local-release-closeout` | CONSOLIDATE |
| `reconcile-account` | OPERATIONS | CURRENT | EXTERNAL_READ | `ops reconcile-account` | CONSOLIDATE |
| `shadow-run` | RESEARCH | CURRENT | LOCAL_STATE | `research shadow` | CONSOLIDATE |
| `shadow-run-real-data` | RESEARCH | CURRENT | EXTERNAL_READ | `research shadow-public` | CONSOLIDATE |
| `strategy-evaluation` | RESEARCH | CURRENT | LOCAL_STATE | `research evaluate` | CONSOLIDATE |
| `strategy-evaluation-extended` | RESEARCH | CURRENT | LOCAL_STATE | `research evaluate-extended` | CONSOLIDATE |
| `fill-simulation-audit` | RESEARCH | CURRENT | LOCAL_STATE | `research fill-audit` | CONSOLIDATE |
| `tiny-live-readiness` | OPERATIONS | CURRENT | LOCAL_STATE | `live readiness` | CONSOLIDATE |
| `discover-markets` | CORE | CURRENT | EXTERNAL_READ | `market discover` | CONSOLIDATE |
| `stream-market` | CORE | CURRENT | EXTERNAL_READ | `market stream` | CONSOLIDATE |
| `paper-trade` | RESEARCH | CURRENT | NONE | `research paper-trade` | CONSOLIDATE |
| `backtest-jsonl` | RESEARCH | CURRENT | LOCAL_STATE | `research backtest` | CONSOLIDATE |
| `live-open-orders` | LIVE | CURRENT | EXTERNAL_READ | `live open-orders` | CONSOLIDATE |
| `live-account-status` | LIVE | CURRENT | EXTERNAL_READ | `live account-status` | CONSOLIDATE |
| `live-cancel-order` | LIVE | CURRENT | EXTERNAL_MUTATION | `live cancel-order` | CONSOLIDATE |
| `live-cancel-market-orders` | LIVE | CURRENT | EXTERNAL_MUTATION | `live cancel-market-orders` | CONSOLIDATE |
| `live-smoke-test` | LIVE | CURRENT | EXTERNAL_MUTATION | `live smoke-test` | CONSOLIDATE |
| `tiny-live-execute` | LIVE | EXPERIMENTAL | EXTERNAL_MUTATION | `live tiny-execute` | CONSOLIDATE |
| `tiny-live-round-trip` | LIVE | EXPERIMENTAL | EXTERNAL_MUTATION | `live tiny-round-trip` | CONSOLIDATE |
| `tiny-live-copy` | LIVE | EXPERIMENTAL | EXTERNAL_MUTATION | `live tiny-copy` | CONSOLIDATE |
| `post-live-reconciliation` | OPERATIONS | CURRENT | LOCAL_STATE | `ops post-live-reconciliation` | CONSOLIDATE |
| `reconcile-live-round-trip` | OPERATIONS | CURRENT | EXTERNAL_READ | `ops reconcile-live-round-trip` | CONSOLIDATE |
| `monitor-live-round-trip` | OPERATIONS | CURRENT | EXTERNAL_READ | `ops monitor-live-round-trip` | CONSOLIDATE |
| `observability-snapshot` | OPERATIONS | CURRENT | LOCAL_STATE | `system observability` | CONSOLIDATE |
| `tiny-live-monitor` | OPERATIONS | CURRENT | EXTERNAL_READ | `ops tiny-live-monitor` | CONSOLIDATE |
| `controlled-second-tiny-live` | LIVE | HISTORICAL | EXTERNAL_MUTATION | `live controlled-second-attempt` | CONSOLIDATE |
| `manual-intervention-live-test` | LIVE | EXPERIMENTAL | EXTERNAL_MUTATION | `live manual-intervention-test` | CONSOLIDATE |
| `live-limit-order` | LIVE | CURRENT | EXTERNAL_MUTATION | `live limit-order` | CONSOLIDATE |
| `control` | OPERATIONS | CURRENT | LOCAL_STATE | `control` | KEEP |

## Evidence and compatibility matrix

Test abbreviations are exact repository paths: `C` is
`tests/unit/cli/test_core.py`, `R` is `tests/unit/cli/test_research.py`, `O` is
`tests/unit/cli/test_operations.py`, `L` is `tests/unit/cli/test_live.py`, `S`
is `tests/unit/cli/test_safety_defaults.py`, `K` is
`tests/integration/test_shadow_control_vertical_slice.py`, and `CON` is
`tests/contract/test_cli_surface.py`.

Documentation abbreviations: `README`, `RUNBOOK` is `docs/OPERATOR_RUNBOOK.md`,
`LIVE` is `docs/LIVE_CONNECTIVITY_SMOKE_TEST.md`, `SHADOW` is
`docs/10-operations/shadow-control-kernel.md`, `SERVER` is
`docs/10-operations/server-deployment.md`, and `HANDOFF` is
`docs/FINAL_HANDOFF.md` plus `docs/RELEASE_HANDOFF.md`.

Safety abbreviations: `LOCAL` means no external mutation; `READ` means a
public or authenticated read-only path with existing redaction/fail-closed
behavior; `SHADOW` means no Live authority; `MUTATION` means the command can
mutate externally only after its existing command-specific dry-run,
acknowledgement, allowlist, geoblock, risk, kill-switch, and reconciliation
controls where applicable. No mutation-capable command is executed by this
migration.

Rollback `R1` means restore visible flat registration and tracked consumer
strings by reverting this migration; the hidden alias already exercises the
same callback. Rollback `R2` means no CLI routing rollback is needed because
the `control` group is unchanged.

| Command | Compatibility obligation | Current consumer | Unique behavior | Tests | Documentation | Scripts / CI | Safety | Rollback |
|---|---|---|---|---|---|---|---|---|
| `health` | Preserve zero-output-error health use | Compose healthcheck, CI, Make, operators | Safe runtime health JSON | C, CON | README, RUNBOOK, SERVER | `compose.yaml`, `Makefile`, CI | LOCAL | R1 |
| `configuration-status` | Preserve redaction and exit status | Operator runbook and tests | Canonical configuration readiness | S, CON | RUNBOOK | None tracked | LOCAL | R1 |
| `operator-status` | Preserve sanitized operator payload | Generated and static runbooks | Guardrail and readiness status | O, CON | RUNBOOK | None tracked | LOCAL | R1 |
| `operator-report` | Preserve formats and output option | Operator runbook | Sanitized JSON/Markdown/HTML report | O, CON | RUNBOOK | None tracked | LOCAL | R1 |
| `deployment-readiness` | Preserve Make and report-builder calls | Make, runbooks, readiness builders | Repository/deployment readiness | O, CON | RUNBOOK | `Makefile` | LOCAL | R1 |
| `operator-runbook` | Preserve generated handoff use | Make and deployment automation | Generated operator procedure | O, CON | RUNBOOK, HANDOFF | `Makefile` | LOCAL | R1 |
| `release-manifest` | Preserve release-builder use | Make and deployment builders | Sanitized release manifest | O, CON | HANDOFF | `Makefile` | LOCAL | R1 |
| `deployment-automation` | Preserve release workflow options | Make and final handoff | Local release artifact orchestration | O, CON | HANDOFF | `Makefile` | LOCAL | R1 |
| `final-handoff` | Preserve current handoff entry point | Make and handoff docs | Consolidated release handoff | O, CON | HANDOFF | `Makefile` | LOCAL | R1 |
| `acceptance-audit` | Preserve no-Live fail-closed behavior | Readiness evidence and tests | Acceptance and Shadow simulation audit | O, S, CON | HANDOFF | None tracked | SHADOW | R1 |
| `production-gap-audit` | Preserve historical evidence generator | Release evidence and tests | Gap and release-freeze report | O, CON | HANDOFF | None tracked | LOCAL | R1 |
| `main-merge-review` | Preserve historical review generator | Release evidence and tests | Human merge-review package | O, CON | HANDOFF | None tracked | LOCAL | R1 |
| `local-release-closeout` | Preserve historical closeout evidence | Release evidence and tests | Local closeout package | O, CON | HANDOFF | None tracked | LOCAL | R1 |
| `reconcile-account` | Preserve authenticated read-only gates | Operator handoff and tests | Account reconciliation and pause evidence | O, CON | HANDOFF | None tracked | READ | R1 |
| `shadow-run` | Preserve Control integration and no-Live gate | Control vertical slice and readiness | Deterministic paper-only Shadow report | R, S, K, CON | SHADOW | None tracked | SHADOW | R1 |
| `shadow-run-real-data` | Preserve public-data-only behavior | Evaluation and handoff workflows | Public-data paper Shadow simulation | R, CON | HANDOFF | None tracked | READ | R1 |
| `strategy-evaluation` | Preserve report inputs and classifications | Readiness workflow and tests | Paper/Shadow evaluation | R, CON | HANDOFF | None tracked | LOCAL | R1 |
| `strategy-evaluation-extended` | Preserve extended report formats | Final handoff and tests | Extended strategy evaluation | R, CON | HANDOFF | None tracked | LOCAL | R1 |
| `fill-simulation-audit` | Preserve conservative models | Readiness workflow and tests | Paper fill realism audit | R, CON | HANDOFF | None tracked | LOCAL | R1 |
| `tiny-live-readiness` | Preserve dry-run-only readiness result | Operator review and tests | Aggregated tiny-Live readiness | O, CON | RUNBOOK | None tracked | LOCAL | R1 |
| `discover-markets` | Preserve public SDK discovery | README, runbook, evidence register | Active-market discovery | C, CON | README, RUNBOOK | None tracked | READ | R1 |
| `stream-market` | Preserve normalized stream options | Operator runbook | Bounded normalized event stream | C, CON | RUNBOOK | None tracked | READ | R1 |
| `paper-trade` | Preserve deterministic local simulation | README and runbook | Strategy-to-Risk-to-paper execution | C, CON | README, RUNBOOK | None tracked | LOCAL | R1 |
| `backtest-jsonl` | Preserve JSONL replay options | Operator runbook | Local replay through risk and paper broker | C, CON | RUNBOOK | None tracked | LOCAL | R1 |
| `live-open-orders` | Preserve acknowledgement and redaction | Operator runbook and tests | Authenticated open-order read | L, S, CON | RUNBOOK | None tracked | READ | R1 |
| `live-account-status` | Preserve signer/funder redaction | Connectivity procedure | Sanitized authenticated account status | L, CON | LIVE | None tracked | READ | R1 |
| `live-cancel-order` | Preserve dry-run default and acknowledgement | Safety tests | Single-order cancellation | S, CON | Migration matrix | None tracked | MUTATION | R1 |
| `live-cancel-market-orders` | Preserve allowlist and dry-run behavior | Operator runbook and tests | Token-scoped cancellation | L, S, CON | RUNBOOK | None tracked | MUTATION | R1 |
| `live-smoke-test` | Preserve connectivity gates and dry-run | Connectivity procedure and tests | Guarded connectivity smoke | L, S, CON | LIVE | None tracked | MUTATION | R1 |
| `tiny-live-execute` | Preserve one-attempt cap and acknowledgement | Safety/evidence tests | One guarded FAK/FOK attempt | L, S, CON | Migration matrix | None tracked | MUTATION | R1 |
| `tiny-live-round-trip` | Preserve dry-run and verified-CI defaults | Operator dry-run procedure and tests | BTC 15-minute round-trip workflow | L, S, CON | RUNBOOK | None tracked | MUTATION | R1 |
| `tiny-live-copy` | Preserve exact experiment contract | Compose profile and experiment evidence | Bounded Copy experiment runner | L, S, CON | SERVER | `compose.yaml` | MUTATION | R1 |
| `post-live-reconciliation` | Preserve report paths and no mutation | Compose monitor and handoff workflow | Post-Live local reconciliation artifacts | O, CON | HANDOFF | `compose.yaml` | LOCAL | R1 |
| `reconcile-live-round-trip` | Preserve read-only account semantics | Operator lifecycle procedure | Delayed-fill reconciliation | O, CON | RUNBOOK | None tracked | READ | R1 |
| `monitor-live-round-trip` | Preserve bounded reads and idempotent alerts | Operator lifecycle procedure | Scheduler-friendly lifecycle monitor | O, CON | RUNBOOK | None tracked | READ | R1 |
| `observability-snapshot` | Preserve sanitized output formats | Generated runbook and handoff | Local observability artifacts | O, CON | RUNBOOK, HANDOFF | None tracked | LOCAL | R1 |
| `tiny-live-monitor` | Preserve read-only service command | Compose monitor and handoff workflow | Continuous tiny-Live monitor report | O, CON | SERVER, HANDOFF | `compose.yaml` | READ | R1 |
| `controlled-second-tiny-live` | Preserve historical safety/evidence path | Historical release evidence and tests | Stricter second-attempt workflow | L, S, CON | HANDOFF | None tracked | MUTATION | R1 |
| `manual-intervention-live-test` | Preserve dry-run and pause evidence | Final handoff and tests | Manual-intervention detection workflow | L, S, CON | HANDOFF | None tracked | MUTATION | R1 |
| `live-limit-order` | Preserve dry-run, allowlist, Risk and geoblock | Operator runbook and safety tests | Tiny post-only limit order | L, S, CON | RUNBOOK | None tracked | MUTATION | R1 |
| `control` | Preserve four-command bounded group | Control runbook and integration slice | SHADOW-only plan/apply/status/history | K, CON | SHADOW | None tracked | SHADOW | R2 |

## Retirement result

No command is deleted. The three HISTORICAL commands remain available under
`ops` or `live` because their report/evidence behavior is unique and no
replacement has been proven. Future retirement must update this matrix and
handle code, tests, documents, scripts, safety implications, and rollback in
one focused pull request.

## Migration and rollback

Tracked consumers should use namespaced commands immediately. An operator can
temporarily use a former flat name if an older deployment wrapper has not yet
been migrated. To roll back the namespace change, revert the CLI registration
and tracked-consumer commits; no database, configuration, credential, SDK, or
runtime-state migration is involved.
