# Issue and Dependency Register

| ID | Type | Item | Status | Exit condition |
|---|---|---|---|---|
| ISS-001 | Missing input | Consolidated Phase 0 project record was not supplied. | Open, non-blocking | Replace reconstructed record if original appears. |
| ISS-002 | Repository | Original Git history is unavailable. | Accepted limitation | Preserve evidence and new history honestly. |
| DEP-001 | SDK | `polymarket-client==0.1.0b11` baseline; official b12 reviewed. | Pinned for migration | Contract-test before upgrade. |
| DEP-002 | Runtime | Python 3.13.14 on Windows. | Verified | Add supported-version CI matrix. |
| DEP-003 | Storage | SQLite local/research persistence. | Accepted | Revisit at documented concurrency/availability triggers. |

