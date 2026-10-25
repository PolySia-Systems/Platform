# ADR-0021: Independent Platform research and operations

Date: 2026-10-16. Status: Accepted under the owner's execution delegation.

## Deferred external source value gate

FUTURE Goldsky integration has no implementation, placeholder UI, account or
enabled connector in this release. Its use case must first demonstrate material
incremental coverage or provenance that current bounded Data API v2 ingestion
cannot supply at an acceptable measured cost. A proposal must verify v2
availability, historical/current coverage and gaps, reorg/finality semantics,
source/event provenance and cross-source deduplication; duplicated observations
do not become independent evidence. Record quota, storage, operating cost,
failure/rollback and access terms before acquisition authorization. Existing
venue-neutral source ports remain the extension boundary. No special framework
or production dependency is added for this deferred possibility.

## Context

CURRENT Platform has native public readers, PolyCop ingestion and separate
intelligence/financial SQLite stores. Native research, reporting and recovery
belong to the same Platform release.

## Decision

Keep one Platform package with separately supervised worker and web processes.
Reuse canonical Shadow/prospective accounting and SQLite Backup API snapshots.
Application reports perform no provider I/O. The web process reads published
reports and submits bounded commands through durable receipts; it cannot open
the financial store for writing, run a shell or access a container socket.

Native discovery has a new, explicit research eligibility contract. Activity
recency is a sampling rule, not trader skill or the PolyCop Alpha policy.
Venue/chain/account identity is shared, while source observations and times
retain attribution. Incomplete walks cannot publish a successful cohort.

New acquisition authority is Platform-owned, numeric, durable and charged before
requests. STOP, expiry and unknown in-flight charges survive restart and restore.
Research processes have no signer or external execution capability.

TARGET deployment promotes an immutable hosted artifact to Helsinki; Nuremberg
is fenced cold recovery. Access/Tunnel protects a loopback origin. Until identity,
permissions and actual denial tests pass, public access is BLOCKED and origin
stays private. This ADR does not certify deployment or observational usefulness.

## Consequences and rollback

One Platform release owns implementation and recovery, including its required
processes, storage and installed assets.
Use separate schema roots for transitions; preserve originals and post-cutover
evidence. Rollback selects the previous compatible artifact and root, with
acquisition stopped and consumed authority reconciled before any resume.


Implementation refinement: the publisher uses read-only SQLite connections and
Backup API snapshots. Its private state directory permits SQLite WAL/SHM
bookkeeping; a physically read-only mount failed the installed-artifact probe.
The Console still has no financial mount. This keeps one financial writer and
avoids falsely declaring an active database immutable. Waitress/PyJWT are the
smaller cached-WSGI equivalent of the default web-stack proposal; notices,
maintenance, test evidence and rollback are in the Console dependency decision.

18 October refinement: new admitted persistent native sessions use the explicit
`continuous-shadow-native-research-v2` configuration. Their financial session has
no arbitrary daily time rollover; event/storage limits, authority/expiry and
explicit drain/finalize still bound operation. Calendar reporting windows do not
reset cash, positions, checkpoints or pending observations. Historical v1/v2
configurations keep their original limits and replay semantics.

Revalidation refreshes only already admitted wallet identities using complete
bounded activity walks and current mapping/fee/book evidence under the same
request/byte authority. Successful receipts bind original cohort and release;
they cannot replace a cohort or manufacture resource admission. Continuous
admission has explicit expiry and is checked on every tick. Changed code/financial
configuration needs a controlled compatible session decision; the deployed stopped
old session is never silently migrated or funded. Existing prepared transitions
remain for explicit safe session changes; automatic daily rollover is not enabled.
