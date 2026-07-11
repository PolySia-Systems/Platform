# Risk Register

| ID | Risk | Likelihood | Impact | Control / owner-visible gate |
|---|---|---:|---:|---|
| RSK-001 | Rename breaks imports, CLI, or operator workflows. | Medium | High | Mechanical inventory, migration tests, full gates, preserved folder and backup. |
| RSK-002 | Beta SDK drift changes signing or responses. | High | High | Exact baseline pin, contract tests, upgrade ADR and rollback. |
| RSK-003 | Venue models remain in core. | High | Medium | Dependency tests and staged domain/port extraction. |
| RSK-004 | Live action runs during structural validation. | Low | Critical | DATA_ONLY overrides, CI exclusion, explicit acknowledgement and one-attempt gates. |
| RSK-005 | Credential value reaches Git or an artifact. | Low | Critical | Ignore rules, value-aware staged scan, redaction tests, safe export. |
| RSK-006 | Invalid historical Git metadata creates false provenance. | High | Medium | Archive pointer; new root commit with no invented history. |
| RSK-007 | Historical documents are mistaken for current status. | Medium | Medium | Archive and document-control hierarchy. |
| RSK-008 | Windows-only lock is treated as universal. | Medium | Medium | Label platform lock; add CI/portable lock before final release. |

