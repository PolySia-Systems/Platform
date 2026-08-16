# Issue and Dependency Register

| ID | Type | Item | Status | Exit condition |
|---|---|---|---|---|
| ISS-001 | Missing input | Consolidated Phase 0 project record was not supplied. | Open, non-blocking | Replace reconstructed record if the original appears. |
| ISS-002 | Repository | Original pre-migration Git history is unavailable. | Accepted limitation | Preserve current Git history, archive evidence, and verified recovery package honestly. |
| ISS-003 | Operations | Local `.env` previously set canonical and deprecated funder variables together. | Closed 2026-07-28 | Deprecated `POLYMARKET_WALLET_ADDRESS` removed; redacted configuration status reports no conflict. |
| ISS-004 | Research | Strategy has one profitable real round trip but no statistically meaningful evidence. | Open, blocks promotion/scaling | Valid historical data, realistic backtest, and large Paper/Shadow samples pass predefined gates. |
| ISS-005 | Operations | Lifecycle monitoring is local and bounded, not continuously scheduled. | Accepted for research cycle | Reassess only when measured operational need justifies scheduling/escalation. |
| DEP-001 | SDK | `polymarket-client==0.2.0`. | Verified | Upgrade only with contract, lock, security, CI, and rollback evidence. |
| DEP-002 | Runtime | Python `>=3.14,<3.15`; locked primary runtime 3.14.6; CI verifies the Python 3.14 line only. | Verified | Change only through a supported-version decision with synchronized metadata, tooling, CI, and documentation. |
| DEP-003 | Storage | SQLite local/research persistence. | Accepted | Revisit only at documented concurrency/availability triggers. |
| DEP-004 | Tooling | Mypy 2.3.0 and Ruff 0.16.0. | Verified | Upgrade only with synchronized lock and reproducibility validation. |
