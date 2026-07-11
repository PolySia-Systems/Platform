# Assumption Register

| ID | Assumption | Confidence | Validation / trigger | Status |
|---|---|---:|---|---|
| ASM-001 | The supplied 328-test implementation is the best available behavior baseline. | High | Baseline passed three times. | Accepted |
| ASM-002 | No external consumer currently requires `pm_trader` or `pm-trader`. | Medium | Revisit if an operator or deployment reports a consumer. | Active |
| ASM-003 | Windows with Python 3.13 is the current owner workstation baseline. | High | Revisit when CI adds other OS/Python versions. | Active |
| ASM-004 | Owner-approved credentials are test-only and operational semantics must remain unchanged. | High | Owner decision only. | Accepted |
| ASM-005 | The missing consolidated Phase 0 record can be reconstructed from approved identity decisions and verified repository evidence. | Medium | Replace if an authoritative original is supplied. | Active |

