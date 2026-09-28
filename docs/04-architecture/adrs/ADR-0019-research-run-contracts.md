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

Collection and image identities are exact lowercase 40-character Git SHAs.
Placeholder or mutable values such as `unknown` and `local` fail before T0.

`CLOSED` remains a lifecycle phase. It is not technical PASS, sufficient
evidence, positive economics, or successful off-host transfer.

## Consequences

Legacy `--profile` / `--code-sha` CLI flags build a compatible Spec.
Unsupported fields, executable expressions, budget expansion, wallet-count
changes, mutable code/image identities, and tampered Plans fail before T0. Old Runs whose Manifest has no
`run_plan_digest` remain readable; a Plan may be written additively from
frozen Manifest fields and the digest recorded. A plan-aware Run that records
`run_plan_digest` but is missing `run-plan.json` fails closed. Rollback is
revert of this ADR and the contract/command/scratch modules.

## Additive runtime contract (2026-09-27)

CURRENT: `research-run-spec-v2` resolves to `research-run-plan-v2` when a
validated `runtime` object is supplied. The Plan freezes the per-wallet v2
source mode, cadence, page/request/time budgets, overlap, and the existing
`target-exposure-v1` reference in its semantic digest. The actual source
factory and restart rebuilder receive those values; a factory that cannot
honor them fails admission. Wallet counts remain bounded to 1–3; the
activity-aware policy still requires exactly three. One or two wallets are
software supported, not measured operational capacity. Reporting remains
on demand; v2 records `retention_days=30` but adds no automatic deletion.
The v2 contract rejects unsupported changes to those fields. Version 1 Plans
and closed bundles retain their original payloads and digests.

## Additive capacity and provisional-readiness contract (2026-09-28)

CURRENT: `research-run-spec-v3` resolves to a separately versioned v3 Plan
for 1–40 requested wallets. The immutable Plan records an explicit ranked or
active policy, the frozen runtime/workload digest, and a capacity disposition.
Start and resume reject unverified or mismatched operational capacity before
the source factory is called. A repeated run id cannot change the frozen
selection count or source budgets. Older Plans retain their semantic digests.

CURRENT: v3 status has an opt-in read-only readiness replay of closed valid
windows. It reports sample rate, exact denominator and evidence ratios,
remaining observations, minimum observation time, and hard profile limit.
The state is provisional even when thresholds are met. The normal healthcheck
does not invoke this potentially expensive replay. Operator stop remains an
idempotent, revision-checked command; neither provisional readiness nor
`CLOSED` alone implies economic acceptance.
