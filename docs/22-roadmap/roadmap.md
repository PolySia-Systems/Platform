# PolySia Roadmap

## Delivered migration stages

- A: baseline, backup, reproducible Windows environment, and honest Git start.
- B: governance, evidence, requirements, ADRs, and document architecture.
- C: canonical `polysia` distribution, namespace, CLI, and operator naming.
- D: venue-neutral domain models, clocks, application ports, and dependency tests.
- E: consolidated Polymarket adapter and pinned SDK contract.
- F: incremental CLI/monitoring/execution decomposition with characterization.
- G: test layers, CI, pre-commit, secret scan, build, dependency-audit gate, and SBOM.
- H: authenticated read-only, paper, local shadow, and public real-data shadow validation.

## Next release-hardening priorities

1. Run `pip-audit --strict` from an approved network or CI and retain the result.
2. Validate GitHub Actions on a configured remote and enable branch protection.
3. Create a portable hash-locked dependency resolution if non-Windows release is required.
4. Upgrade the Polymarket SDK only through the documented contract/rollback process.
5. Continue CLI command-group dependency injection and oversized-service extraction.
6. If the owner explicitly authorizes one specific state-changing test, execute only
   the existing tiny-live gated procedure and retain complete reconciliation evidence.

## Explicitly deferred

Multi-venue expansion, Web3/DeFi breadth, copy trading, advanced portfolio
optimization, institutional infrastructure, microservices, cloud deployment,
and machine learning are not commitments in this modernization delivery.
