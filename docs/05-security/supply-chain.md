# Software Supply-Chain Controls

## Local gates

- `python -m polysia.security.secret_scan`
- `python -m pip_audit --strict`
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
- Dependency audit: inconclusive locally. `pip-audit` could not query the PyPI
  advisory endpoint because the workstation proxy closed the connection. No
  clean or vulnerable result is inferred from that network failure; CI retains
  the same strict audit gate for a network-enabled run.

## CI

Windows CI tests Python 3.11 and 3.13 with DATA_ONLY safety overrides. A separate
supply-chain job audits dependencies and publishes an SBOM artifact. GitHub
Actions and pip dependencies receive weekly Dependabot review.

## Limitations

The Windows lock is the verified owner-workstation snapshot. CI installation
from `pyproject.toml` validates supported Python versions but is not yet a
cross-platform hash-locked resolution. Adding a portable lock remains a release
hardening item. CODEOWNERS and repository protection require the owner's GitHub
account/repository configuration and cannot be invented locally.

The local dependency-vulnerability result remains open until `pip-audit` can
reach PyPI or an approved advisory mirror. This does not affect the successful
package build, SBOM generation, or dependency-consistency check.
