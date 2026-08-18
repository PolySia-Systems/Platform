# Architecture Overview

## CURRENT

PolySia is one Python modular monolith with inward dependency boundaries:

`interfaces and adapters -> application contracts -> domain`

Domain and application code do not import Polymarket SDK types or adapter
models. Venue identifiers, signer/funder semantics, fee schedules, tick/minimum
rules, geoblock results, and venue errors are translated at the adapter
boundary.

The current executable-intent path is:

`Strategy -> independent Risk -> Execution -> Polymarket Adapter -> Venue`

The bounded round-trip slice adds persistent authorization, one FAK entry,
actual-fill reconciliation, one position-sized GTC exit, durable checkpoints,
SQLite order/fill/position/ledger state, post-exit reconciliation, and bounded
read-only lifecycle monitoring. Risk, geoblock, kill switch, allowlist, caps,
acknowledgement, duplicate prevention, and fail-closed uncertainty remain
non-bypassable.

The minimal Strategy Registry is CURRENT. It stores versioned definitions,
lifecycle state, run evidence, and explicitly unrated performance summaries; it
is not a generalized multi-strategy orchestrator.

The first Control Kernel slice is CURRENT for the deterministic
`stale-price@0.1.0` Shadow path only. Its CLI can plan and apply
`RUNNING <-> PAUSED` with immutable SQLite revisions, optimistic concurrency,
idempotency, separate desired/observed state, and append-only audit evidence.
The in-process intent boundary prevents new strategy intents while paused; it
does not stop Risk, reconciliation, monitoring, or emergency controls and it
cannot reach Live trading.

The owner-bounded Tiny Live Copy path is CURRENT only as an experimental,
persistently capped exception. Its fourth run created one accepted unfilled
Post-only order and stopped `FAILED_SAFE` when one immediate read could not
confirm cancellation. Later authenticated reads proved zero open orders,
confirmed fills, exposure, and experiment cost. This is safety evidence, not
general Copy Trading or production-readiness evidence.

## TARGET

Generalized intent aggregation/conflict resolution, portfolio/capital
allocation, OMS or Transaction Manager, generalized ledger, execution router,
adapter registry, generalized runtime parameter mutation, and continuous
control reconciliation are approved target concepts only. They must not be
shown or described as part of the current executable path.

## FUTURE

Additional venues, Web3/DeFi execution, cloud/distributed infrastructure,
machine learning, Control Kernel Web/API/AI interfaces, Live operational
control, generalized or permanent Copy Trading, and institutional availability
are optional future directions requiring evidence and separate decisions.

## EXTERNAL

Polymarket APIs, market resolution, custody/wallet behavior, GitHub, CI runners,
and the Windows time source are external systems. PolySia validates and
reconciles their observable state but does not control their availability or
truth.
