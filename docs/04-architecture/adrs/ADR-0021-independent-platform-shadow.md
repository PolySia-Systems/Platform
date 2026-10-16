# ADR-0021: Independent Platform research and operations

Date: 2026-10-16. Status: Accepted under the owner's execution delegation.

## Context

CURRENT Platform has native public readers, PolyCop ingestion and separate
intelligence/financial SQLite stores. Its optional WI workflow starts another
application. That workflow remains a historical import consumer until native
replacement and retained-import parity are verified; it is not a deployment
dependency for the new Platform epoch.

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
WI's stopped campaigns and exhausted authority are never inherited or renewed.
Research processes have no signer or external execution capability.

TARGET deployment promotes an immutable hosted artifact to Helsinki; Nuremberg
is fenced cold recovery. Access/Tunnel protects a loopback origin. Until identity,
permissions and actual denial tests pass, public access is BLOCKED and origin
stays private. This ADR does not certify deployment or observational usefulness.

## Consequences and rollback

One release owns implementation and recovery. No WI checkout, process, mounted
volume or private-repository credential may be required by the final artifact.
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
