# ADR-0019: Contract-Driven Research Runs and Manifest Ownership

- Status: Accepted
- Date: 2026-09-20

## Context

The bounded research Runner already prepares, collects, verifies, and closes
one workspace. Operators still expressed intent through ad-hoc CLI flags.
Concurrent `stop` could independently rewrite `run-manifest.json` while the
worker held an in-memory copy. Large-bundle restore and compatibility copies
could fall through to the container `/tmp` tmpfs.

## Decision

CURRENT: a versioned `research-run-spec-v1` resolves deterministically to an
immutable `research-run-plan-v1`. Admission rechecks DATA_ONLY, Live-disabled,
disk, memory, and one host-wide admission lock immediately before start/resume
and verify. The default lock stem is `/var/lib/polysia/research-runner-admission`
and does not follow the workspace parent; `POLYSIA_RESEARCH_ADMISSION_LOCK` or
the constructor may override it for isolated tests. The worker is the only
writer of Manifest state. Clients persist a stop command (id, content
fingerprint, expected revision, disposition) and a stop-request file; repeating
the same command returns the recorded disposition. Large restore and analysis
copies use an operation-owned scratch directory beside the bundle or database,
with filesystem preflight.

Safety remains independent of Spec/Plan content. Canary/Main profiles and the
three-wallet Polycop default are unchanged. Control Kernel modules are not
imported; only the existing local exclusive lock and command-id pattern are
reused.

`CLOSED` remains a lifecycle phase. It is not technical PASS, sufficient
evidence, positive economics, or successful off-host transfer.

## Consequences

Legacy `--profile` / `--code-sha` CLI flags build a compatible Spec.
Unsupported fields, executable expressions, budget expansion, wallet-count
changes, and tampered Plans fail before T0. Old Runs whose Manifest has no
`run_plan_digest` remain readable; a Plan may be written additively from
frozen Manifest fields and the digest recorded. A plan-aware Run that records
`run_plan_digest` but is missing `run-plan.json` fails closed. Rollback is
revert of this ADR and the contract/command/scratch modules.
