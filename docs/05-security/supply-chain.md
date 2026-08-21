# Software Supply-Chain Controls

## Local gates

- `python -m polysia.security.secret_scan`
- `python -m pip_audit --strict --vulnerability-service osv`
- `python -m build`
- `cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json`
- `pre-commit run --all-files`

The secret scanner reads only Git-tracked files, reports rule and path without
echoing matched values, and rejects tracked `.env`, key, and PEM files. Runtime
`.env` remains ignored and unchanged.

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
Executable Python changes run complete quality validation on canonical Linux;
full Windows compatibility runs weekly, manually, and for verified
Windows-sensitive changes. The container job runs only for Docker, deployment,
runtime-lock, entrypoint, health, backup, state-path, or related executable
configuration changes. The supply-chain job performs a strict OSV audit and
publishes a CycloneDX SBOM for dependency changes, on a weekly schedule, and by
manual dispatch. GitHub Actions and pip dependencies receive weekly Dependabot
review.

A final fail-closed CI Gate checks that every job required by the risk-based
change map succeeded. Manual comprehensive validation covers migrations and
uncertain changes without making all future CI-only pull requests permanently
run unrelated jobs.

## Limitations

The Conda lock is the verified Windows owner-workstation snapshot. The exact
pip lock is portable across compatible Windows and Linux Python 3.14
environments but is not hash-locked; adding hashes remains a release-hardening
item. CODEOWNERS and repository protection require the owner's GitHub
account/repository configuration and cannot be invented locally.

The default PyPI advisory endpoint remains unavailable through the workstation
proxy. OSV provided the successful strict audit result; future release evidence
should record the selected advisory service and timestamp.
