# ADR-0012: In-Process Shadow Control Kernel

- Status: Accepted
- Date: 2026-08-17

## Context

PolySia currently exposes deployment and bootstrap configuration through
`AppSettings`, while its deterministic `shadow-run` path invokes a strategy,
independent Risk, and the paper broker directly inside the modular monolith.
Changing operational intent through environment variables would mix deployment
configuration with runtime control. Building a service, daemon, or generalized
strategy orchestrator would exceed current needs and contradict the approved
modular-monolith baseline.

The first control capability must prove one complete, safe path without implying
that generalized orchestration, a web console, AI control, or Live control exists.
The selected boundary is the deterministic `stale-price@0.1.0` Shadow path,
immediately before `BaseStrategy.on_market_event` can emit new order intents.

## Decision

Implement a venue-neutral Control Kernel inside the existing Python process. The
first CURRENT slice supports only `SHADOW` and only two operational states:

- `RUNNING`: the selected Shadow strategy may generate new pre-risk intents.
- `PAUSED`: the selected Shadow strategy generates no new intents.

Lifecycle status remains separate. `EXPERIMENTAL`, `PAPER`, `SHADOW`,
`LIMITED_LIVE`, `SUSPENDED`, and `RETIRED` describe strategy maturity; `RUNNING`
and `PAUSED` describe the requested operational behavior of one supported Shadow
runtime boundary.

`PAUSED` is not shutdown, cancel-all, position closure, or Kill Switch
activation. Risk, execution lifecycle handling, open-order and position
management, reconciliation, monitoring, and emergency controls remain
independent and available. This slice never authorizes or reaches Live trading.

The command flow is:

`CLI -> typed command -> plan -> validation and policy -> apply(expected revision)`

`-> immutable desired-state revision -> in-process reconciliation`

`-> Shadow intent boundary -> observed state -> append-only audit evidence`

Policy determines whether approval is required. The low-risk Shadow-only state
transition in this slice does not require a separate owner approval, but apply is
still an explicit operator command. Actor labels are audit metadata, not an
authentication or authorization system.

## State and consistency semantics

Desired and observed state are distinct:

- Desired State records what the operator requested.
- Observed State records only what the Shadow runtime boundary acknowledged.

Writing Desired State alone never proves reconciliation. A failed or unverifiable
transition records `FAILED` and `UNKNOWN` or the last verified observed state; it
must not report optimistic success.

Desired State uses immutable, monotonically increasing revisions. Revision zero
is the compatibility baseline representing the pre-control Shadow behavior,
`RUNNING`; it is not a mutable database row. Every accepted change appends a new
revision. Apply requires the plan's expected revision. A stale plan fails and
must be rebuilt against the new revision.

Every apply command has an idempotency key. Replaying the same key and payload
returns the original result without another revision. Reusing a key with a
different payload fails. Revision, command result, observation, and audit writes
are committed atomically in SQLite.

A future configuration revert will create a new forward revision based on an
older desired state. It will not delete history and cannot undo orders, fills, or
other events that already occurred in an external system.

## Configuration boundaries

The Control Kernel owns only explicitly supported operational desired state:

- Code and algorithm changes continue through code review, tests, CI, and
  deployment.
- Bootstrap, deployment settings, and secrets remain in `AppSettings`, protected
  environment variables, and deployment configuration.
- Hard Risk, geoblock, allowlists, Live authorization, Kill Switch, and emergency
  policy remain independently authoritative and non-bypassable.

The existing Strategy Registry remains responsible for definitions, versions,
lifecycle status, run evidence, and performance summaries. It is not converted
into an orchestrator by this decision.

## CURRENT, TARGET, and FUTURE

After verified implementation, CURRENT is limited to CLI planning, applying,
status, and history for `RUNNING <-> PAUSED` on the selected deterministic
Shadow path, backed by SQLite and synchronous in-process reconciliation.

TARGET includes additional explicitly declared runtime-mutable capabilities,
more strategies, and a continuous reconciler only if measured runtime needs
justify them. Web, API, AI, natural-language control, generalized orchestration,
RBAC, distributed configuration, additional venues, and every form of Live
operational control remain FUTURE or require separate decisions and safety
evidence.

## Consequences and risks

The slice gives every future interface one typed capability instead of copying
business logic. Immutable history, concurrency checks, and idempotency improve
operator safety and reproducibility.

The process-local runtime acknowledgement is deliberately narrow. It does not
prove that a long-running worker exists, and it does not create one. A later
runtime may rehydrate the latest desired revision and acknowledge it at the same
intent boundary, but continuous reconciliation is outside this decision.

SQLite serializes state transitions for the current single-process deployment.
Multi-process or distributed control would require a new concurrency and
availability decision rather than silently extending this design.

## Validation and rollback

Validation must prove the real Shadow intent boundary emits no new intents while
paused, preserves existing running behavior, persists revisions across restart,
rejects stale and conflicting commands, replays identical commands
idempotently, rolls back failed database transactions, and never contacts a
Live venue.

Code rollback is a normal revert of the implementation and additive SQLite
objects. Existing tables and trading state are not rewritten. Retained control
tables are inert without the Control Kernel and preserve audit evidence; any
decision to remove them requires a separate reviewed migration.
