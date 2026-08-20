# ADR-0011: Python 3.14 and Polymarket SDK 0.2 Baseline

- Status: Accepted
- Date: 2026-07-28
- Last amended: 2026-08-21
- Supersedes: ADR-0005

## Context

Before this decision, PolySia's verified baseline used Python 3.13.14 and
`polymarket-client==0.1.0b11`. The promoted and locked workstation baseline is
Python 3.14.6. The official Polymarket unified SDK left beta and released
`polymarket-client==0.2.0`.

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
- Configure Ruff, Mypy, Windows quality, and Linux smoke validation for Python
  3.14 only.
- Pin the official unified Polymarket SDK to `0.2.0`.
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
parameters, and model fields consumed by PolySia. The 0.2.0 `condition_id`
field is explicitly covered while the deprecated `market` compatibility field
remains accepted at the adapter boundary.

Python 3.14 is the only CI target. Python 3.14 wheel installation, CLI smoke,
complete repository validation, strict dependency audit, and SBOM generation
are required before promotion. Removing Python 3.11 and 3.13 is an intentional
compatibility break for environments on those minor versions; it does not
change strategy, risk, execution, reconciliation, credential, or live-control
behavior.

Routine pull requests run lightweight diff, local path/link, and secret checks.
Full Windows/Linux, container, and supply-chain gates run only for the relevant
changed paths, while supply-chain validation also runs weekly and on manual
dispatch.

## Rollback

Revert the 2026-08-16 compatibility and CI optimization commit to restore the
previous package metadata, tool targets, and Python 3.11/3.13/3.14 CI matrix.
Recreate and revalidate the older environment from the reverted definitions if
that compatibility is required. Never alter signer, funder, wallet, or
credential values as part of dependency rollback.
