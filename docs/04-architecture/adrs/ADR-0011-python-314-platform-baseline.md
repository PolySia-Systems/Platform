# ADR-0011: Python 3.14 and Polymarket SDK 0.2 Baseline

- Status: Accepted
- Date: 2026-07-28
- Supersedes: ADR-0005

## Context

PolySia's verified baseline used Python 3.13.14 and
`polymarket-client==0.1.0b11`. Python 3.14.6 is the latest stable Python 3.14
maintenance release. The official Polymarket unified SDK has left beta and
released `polymarket-client==0.2.0`.

The existing environment also contained vulnerable `setuptools==82.0.1`.
Project delivery requires a reproducible Windows workstation baseline, a
portable Python dependency lock for Linux deployment, and CI evidence across
the supported Python range.

## Decision

- Make CPython 3.14.6 the primary development runtime.
- Continue supporting Python 3.11 and 3.13, and add Python 3.14 to CI.
- Pin the official unified Polymarket SDK to `0.2.0`.
- Pin direct development tools and the portable transitive lock to the
  versions verified by `POLYSIA-UPGRADE-006`.
- Require `setuptools==83.0.0`.
- Keep the SDK confined to the existing Polymarket adapter boundary.

No strategy, risk, execution, reconciliation, credential, or live-control
behavior changes as part of this decision.

## Compatibility evidence

The SDK surface contracts verify the public and secure client methods, order
parameters, and model fields consumed by PolySia. The 0.2.0 `condition_id`
field is explicitly covered while the deprecated `market` compatibility field
remains accepted at the adapter boundary.

Python 3.11, 3.13, and 3.14 remain CI targets. Python 3.14 wheel installation,
CLI smoke, complete repository validation, strict dependency audit, and SBOM
generation are required before promotion.

## Rollback

Use the external Python 3.13 rollback export created before promotion or revert
this change to restore the previous Git-pinned environment definitions. Never
alter signer, funder, wallet, or credential values as part of dependency
rollback.
