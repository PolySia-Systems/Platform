# Issue and Dependency Register

| ID | Type | Item | Status | Exit condition |
|---|---|---|---|---|
| ISS-001 | Missing input | Consolidated initial project record was not supplied; the [reconstructed record](../../99-archive/discovery/phase-0-project-record.md) is archived. | Open, non-blocking | Replace the reconstructed record if the original appears. |
| ISS-002 | Repository | Original pre-migration Git history is unavailable. | Accepted limitation | Preserve current Git history, archive evidence, and verified recovery package honestly. |
| ISS-003 | Operations | Local `.env` previously set canonical and deprecated funder variables together. | Closed 2026-07-28 | Deprecated `POLYMARKET_WALLET_ADDRESS` removed; redacted configuration status reports no conflict. |
| ISS-004 | Research | Strategy has one profitable real round trip but no statistically meaningful evidence. | Open, blocks promotion/scaling | Valid historical data, realistic backtest, and large Paper/Shadow samples pass predefined gates. |
| ISS-005 | Operations | Lifecycle monitoring is local and bounded, not continuously scheduled. | Accepted for research cycle | Reassess only when measured operational need justifies scheduling/escalation. |
| DEP-001 | SDK | Approved declaration in [pyproject.toml](../../../pyproject.toml); resolved stack in [runtime lock](../../../locks/requirements-runtime-py314.txt). | Source-owned | Upgrade only with contract, lock, security, CI and rollback evidence. |
| DEP-002 | Runtime | Supported Python in [pyproject.toml](../../../pyproject.toml); tested patch in [CI](../../../.github/workflows/ci.yml) and image in [Dockerfile](../../../Dockerfile). | Source-owned | Synchronize supported-version decisions and exact release evidence. |
| DEP-003 | Storage | SQLite local/research persistence. | Accepted | Revisit only at documented concurrency/availability triggers. |
| DEP-004 | Tooling | Declared tools in [pyproject.toml](../../../pyproject.toml), resolved in [development lock](../../../locks/requirements-dev-py314.txt). | Source-owned | Validate coherent updates and reproducible builds. |
