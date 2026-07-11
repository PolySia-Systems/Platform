# Delivery and Rollback

## Delivery contents

- Canonical source is the current Git `main` branch.
- `environment.yml`, `locks/conda-win-64.lock`, and `locks/pip-win-64.lock`
  describe the verified owner-workstation environment.
- `scripts/export-source.ps1` creates a credential-free source archive outside
  the repository and excludes the preserved legacy folder and generated data.
- Generated build, SBOM, shadow, and release evidence remains under ignored
  artifact directories.
- Phase handoffs are under `docs/18-ai-handoffs`.

## Recovery layers

1. Revert a phase commit for a narrow rollback.
2. Recreate the current runtime from the environment and lock files.
3. Use the preserved `Polymarket Python SDK` folder for side-by-side comparison.
4. Use the external pre-migration backup for complete recovery, including the
   original local configuration, only in an access-controlled context.

The legacy folder and old `polymarket` Conda environment are deliberately not
deleted in this delivery. Their removal requires an owner review after final
verification and confirmation that no external consumer still depends on them.

Never copy `.env`, keys, account identifiers, databases, or generated live
evidence into a source archive or tracked handoff.
