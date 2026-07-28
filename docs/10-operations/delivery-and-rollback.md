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
3. Use the external `PolySia-py313-rollback-*` environment export for a
   dependency/runtime rollback.
4. Use the preserved `Polymarket Python SDK` folder for side-by-side comparison.
5. Use the external pre-migration backup for complete recovery, including the
   original local configuration, only in an access-controlled context.

The legacy project folder remains preserved. The owner removed the old
`polymarket` Conda environment before the Python 3.14 upgrade; PolySia does not
depend on it.

Never copy `.env`, keys, account identifiers, databases, or generated live
evidence into a source archive or tracked handoff.
