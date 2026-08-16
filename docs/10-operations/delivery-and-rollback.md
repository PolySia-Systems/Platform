# Delivery and Rollback

## Delivery contents

- Canonical source is the current Git `main` branch.
- `environment.yml`, `locks/conda-win-64.lock`, and `locks/pip-py314.lock`
  describe the verified Python 3.14 owner-workstation environment. The pip lock
  is version-pinned and portable to compatible Windows and Linux Python 3.14
  installations; the explicit Conda lock is Windows-specific.
- `scripts/export-source.ps1` creates a credential-free source archive outside
  the repository and excludes the preserved legacy folder and generated data.
- Generated build, SBOM, shadow, and release evidence remains under ignored
  artifact directories.
- Phase handoffs are under `docs/18-ai-handoffs`.

## Recovery layers

1. Revert a phase commit for a narrow rollback.
2. Recreate the current runtime from the environment and lock files.
3. Revert the Python support decision and recreate the reverted environment if
   an emergency rollback requires Python 3.11 or 3.13; current `main` supports
   only Python 3.14.
4. Use the preserved `Polymarket Python SDK` folder for side-by-side comparison.
5. Use the external pre-migration backup for complete recovery, including the
   original local configuration, only in an access-controlled context.

The legacy project folder remains preserved. The owner removed the old
`polymarket` Conda environment and earlier workstation recovery exports after
verification; PolySia does not depend on them.

Never copy `.env`, keys, account identifiers, databases, or generated live
evidence into a source archive or tracked handoff.

## Tiny Live Copy 002 rollback

The reliability repair adds only additive SQLite tables for discovery state,
per-alias read checkpoints, and sanitized pending read events. Before the
authorized run starts, rollback is a checkout of the previously recorded
merged commit followed by an image rebuild; the additive empty tables may
remain.

After launch, preserve the database, run reports, cooldown state, and candidate
cleanup evidence. Do not roll back or stop the worker while an entry order,
position, or exit exists without an explicit containment plan. If the worker is
flat, stop the profile, reconcile authenticated account state read-only, verify
report checksums, and retain the report directory. Never delete the prior
failed-safe run or reuse either authorization or run identifier.
