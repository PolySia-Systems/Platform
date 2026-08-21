# ADR-0011: Python 3.14 and Polymarket SDK 0.6 Baseline

- Status: Accepted
- Date: 2026-07-28
- Last amended: 2026-08-21
- Supersedes: ADR-0005

## Context

Before this decision, PolySia's verified baseline used Python 3.13.14 and
`polymarket-client==0.1.0b11`. The promoted and locked workstation baseline is
Python 3.14.6. The official Polymarket unified SDK left beta and released
`polymarket-client==0.2.0`. Official stable releases 0.3.0 through 0.6.0 were
subsequently reviewed on 2026-08-21, and 0.6.0 is the latest compatible stable
release.

The existing environment also contained vulnerable `setuptools==82.0.1`.
Project delivery requires a reproducible Windows workstation baseline, a
portable Python dependency lock for Linux deployment, and CI evidence across
the supported Python line. The 2026-08-16 CI optimization decision removes
Python 3.11 and 3.13 support so routine validation can focus on the current
runtime without redundant compatibility jobs.

## Decision

- Support only the CPython 3.14 minor line, expressed as `>=3.14,<3.15` in
  package metadata. Python 3.11 and 3.13 are no longer supported.
- Keep CPython 3.14.6 as the locked owner-workstation and container baseline;
  CI resolves the latest available Python 3.14 maintenance release.
- Configure canonical Linux quality validation for Python 3.14 only. Keep full
  Windows compatibility validation weekly, manually dispatchable, and
  conditional on verified Windows-sensitive changes rather than on ordinary
  pull requests.
- Pin the official unified Polymarket SDK to `0.6.0`.
- Pin direct development tools and the portable transitive lock to versions
  verified by repository quality and supply-chain gates.
- Require `setuptools==84.0.0` in the final pip-managed development
  environment. Retain `setuptools==83.0.0` only as the latest Python 3.14
  bootstrap available from the Conda `defaults` channel; installing the
  portable pip lock deterministically promotes the completed environment to
  `84.0.0`.
- Keep the SDK confined to the existing Polymarket adapter boundary.

No strategy, risk, execution, reconciliation, credential, or live-control
behavior changes as part of this decision.

## Compatibility and validation

The SDK surface contracts verify the public and secure client methods, order
parameters, signer/private-key and funder/wallet creation inputs, and model
fields consumed by PolySia. The `condition_id` field is explicitly covered
while the deprecated `market` compatibility field remains accepted at the
adapter boundary. The 0.6.0 migration preserves the existing transitive
dependency set and does not adopt its new perps or combo RFQ capabilities.

Python 3.14 is the only CI target. Python 3.14 wheel installation, CLI smoke,
complete repository validation, strict dependency audit, and SBOM generation
are required before promotion. Removing Python 3.11 and 3.13 is an intentional
compatibility break for environments on those minor versions; it does not
change strategy, risk, execution, reconciliation, credential, or live-control
behavior.

Routine pull requests run lightweight diff, local path/link, Standards, and
secret checks. Executable Python changes add canonical Linux compile, Ruff,
Mypy, complete Pytest, environment-integrity, and applicable locked-wheel
validation. Full Windows compatibility is periodic or Windows-sensitive; it is
not an ordinary pull-request gate. Container and supply-chain gates remain
risk-based, while Windows compatibility and supply-chain validation also run
weekly and on manual dispatch.

This Linux-first policy reflects the controlled Ubuntu/Docker runtime while
retaining evidence for the owner Windows workstation. A Windows-only regression
may be detected by conditional or scheduled validation after an ordinary pull
request has merged. Shared or uncertain CI-control changes fail closed to
comprehensive validation, and an explicit manual full-validation mode remains
available.

## Rollback

Revert the Linux-first CI policy commit to restore Windows quality on relevant
ordinary pull requests and the separate Linux smoke job. Reverting the earlier
2026-08-16 compatibility decision would additionally restore the obsolete
Python 3.11/3.13/3.14 matrix and requires a separate compatibility review.
Never alter signer, funder, wallet, or credential values as part of rollback.
