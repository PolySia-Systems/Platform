# Software Supply-Chain Controls

## Local gates

- `python -m polysia.security.secret_scan`
- `python -m pip_audit --strict --vulnerability-service osv`
- `python -m build`
- `cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json`
- `python scripts/dependency_locks.py check`
- `pre-commit run --all-files`

The secret scanner reads only Git-tracked files, reports rule and path without
echoing matched values, and rejects tracked `.env`, key, and PEM files. Runtime
`.env` remains ignored and unchanged.

`pyproject.toml` is the only manually maintained pip declaration. Generated
outputs are `locks/requirements-runtime-py314.txt` and
`locks/requirements-dev-py314.txt`. They are produced by pip-tools 7.6.1 from
`pyproject.toml` (development extras only on the development lock) with a
stable header and no pip-compile annotations, so Linux and Windows Python 3.14
can verify the same committed pins. Do not hand-edit generated rows. Conventional `.txt` names let GitHub's dependency
graph see the resolved graph; Dependabot `exclude-paths` prevents duplicate
version PRs against those generated files.

```bash
python scripts/dependency_locks.py check
python scripts/dependency_locks.py refresh --scope pip --upgrade
python scripts/dependency_locks.py refresh --scope conda
make dependency-locks-check
make dependency-locks
```

`check` never selects newer versions. `refresh --scope pip --upgrade` is the
only command that intentionally upgrades pip packages. Conda refresh is only
for Python/bootstrap/environment-owner changes.

## CURRENT automation

Dependabot discovers all direct pip and GitHub Actions updates. It does not
hide runtime, SDK, or major updates. Native lock regeneration from custom
pip-compile outputs is not assumed; if a Dependabot pip PR omits generated
locks, trusted base-branch code generates them and a separate write job
commits only those lock files to the Dependabot branch, then dispatches CI.
Unattended merge is limited to verified low-risk development or Actions patch
updates after `CI Gate`. Runtime, SDK, Python/Conda, major, `0.x` minor,
trading/financial, and sensitive security changes stay open for owner review.

Weekly scheduled refresh uses the same pip-compile command. It opens no PR
when the resolution is unchanged. Runtime lock drift in that PR requires
review.

## 2026-07-11 verification evidence

- Package build: passed for the source distribution and wheel.
- CycloneDX SBOM: generated as specification 1.6 with 121 components at
  `artifacts/sbom.json`; the generated directory is intentionally ignored.
- Environment integrity: `pip check` passed.
- Dependency audit: passed with `pip-audit --strict` using the OSV advisory
  service; no known vulnerabilities were reported. The default PyPI advisory
  endpoint remained unreachable through the workstation proxy, so OSV is the
  standardized local and CI service.

## CI

CI supports Python 3.14 only and keeps DATA_ONLY safety overrides. Pull requests
always run diff, local path/link, Standards, and tracked-file secret checks.
Executable Python changes run complete quality validation on canonical Linux,
including deterministic lock verification; full Windows compatibility runs
weekly, manually, and for verified Windows-sensitive changes. The container job
runs only for Docker, deployment, runtime-lock, entrypoint, health, backup,
state-path, or related executable configuration changes. The supply-chain job
performs a strict OSV audit and publishes a CycloneDX SBOM on canonical Linux
for dependency changes, on a weekly schedule, and by manual dispatch. It
retains a separate allowed-range wheel compatibility smoke without adding that
resolution work to ordinary source pull requests. GitHub Actions and pip
dependencies receive weekly Dependabot review.

A final fail-closed CI Gate checks that every job required by the risk-based
change map succeeded. Manual comprehensive validation covers migrations and
uncertain changes without making all future CI-only pull requests permanently
run unrelated jobs.

## Rollback

1. Revert the dependency automation merge on `main`.
2. Disable repository auto-merge and the `main` ruleset/branch protection.
3. Disable Dependabot Security Updates if they must be removed with the revert.
4. Restore previous pip lock filenames only by reverting the same merge; do not
   keep both generated generations.

## Limitations

The Conda lock is the verified Windows owner-workstation snapshot. The exact
pip locks are portable across compatible Windows and Linux Python 3.14
environments but are not hash-locked; adding hashes remains a release-hardening
item. CODEOWNERS remains optional owner GitHub configuration.

The default PyPI advisory endpoint remains unavailable through the workstation
proxy. OSV provided the successful strict audit result; future release evidence
should record the selected advisory service and timestamp.
