# C4 System Context

- **Diagram ID:** PSA-ARCH-02
- **Purpose:** Explain in one view who uses PolySia, what it owns, and which responsibilities remain external.
- **Scope:** C4 Person and Software System level only.
- **Architecture status:** MIXED
- **Audience:** Non-technical owner, developers, risk reviewers, and architecture reviewers.
- **Source commit:** `449f1c308fc74bd2a541e0e905f281fd19e5cd9b`

## Mermaid diagram

Canonical source: [`02-c4-system-context.mmd`](../sources/02-c4-system-context.mmd)

```mermaid
flowchart LR
  Operator["Person: Owner / Operator\nRuns commands, reviews evidence, controls live gates\n[CURRENT]"]:::current
  Researcher["Person: Researcher\nEvaluates strategies in replay, paper, and shadow\n[CURRENT]"]:::current
  Auditor["Person: Risk Reviewer / Auditor\nIndependent review\n[TARGET]"]:::target

  PolySia["Software System: PolySia\nNormalizes market data, produces pre-risk intents,\ncontrols execution, state, reconciliation, and reporting\n[CURRENT]"]:::current

  Polymarket["Software System: Polymarket\nMarket data, account reads, order endpoints\n[EXTERNAL]"]:::external
  GitProvider["Software System: Git / CI provider\nVersion control and configured quality workflow\n[EXTERNAL]"]:::external
  LocalOS["System boundary: Owner workstation\nConda, local files, SQLite, secrets\n[EXTERNAL]"]:::external
  FutureVenues["Software Systems: Additional venues\n[FUTURE]"]:::future

  Operator -->|CLI commands and explicit approvals| PolySia
  Researcher -->|data, configurations, research runs| PolySia
  PolySia -->|sanitized reports and stop status| Operator
  Auditor -.->|reviews traceability and risk evidence| PolySia
  PolySia -->|public reads, authenticated reads, guarded execution| Polymarket
  PolySia -->|source and CI configuration| GitProvider
  LocalOS -->|hosts one Python process and persistent files| PolySia
  PolySia -.->|future generic adapter contracts| FutureVenues

  subgraph RESPONSIBILITY["PolySia responsibility boundary"]
    R1["Owns: intent, risk gates, execution control, state, reconciliation"]:::current
    R2["Does not own: venue availability, custody, resolution, external CI service"]:::external
  end

  subgraph LEGEND["Legend"]
    L1["CURRENT solid"]:::current
    L2["TARGET dashed"]:::target
    L3["FUTURE dotted"]:::future
    L4["EXTERNAL gray"]:::external
  end

  classDef current fill:#FFFFFF,stroke:#0F172A,stroke-width:2px,color:#0F172A;
  classDef target fill:#F1F5F9,stroke:#2563EB,stroke-width:2px,stroke-dasharray:6 4,color:#0F172A;
  classDef future fill:#F1F5F9,stroke:#64748B,stroke-width:2px,stroke-dasharray:2 5,color:#475569;
  classDef external fill:#F1F5F9,stroke:#64748B,stroke-width:1.5px,color:#475569;
```

## Legend

CURRENT is solid, TARGET is dashed, FUTURE is dotted, EXTERNAL is gray, safety is amber, emergency/block is red, and approval/healthy is green. Arrow meanings follow [diagram conventions](../diagram-conventions.md).

## Main reading path

Start with the owner and researcher, then PolySia, then Polymarket, the workstation, Git/CI, and future venue systems.

## Current implementation mapping

The `polysia` package owns normalization, intent generation, risk gating, execution control, state, reconciliation, and reports. Polymarket availability, custody, market resolution, and external CI service operation remain external.

## Target/future elements

An independent reviewer role and additional venue systems are TARGET/FUTURE.

## Related repository files

`README.md`, `pyproject.toml`, `src/polysia/`, `docs/00-governance/project-charter.md`

## Related tests

`tests/migration/test_identity.py`, `tests/integration/test_paper_vertical_slice.py`, `tests/architecture/test_boundaries.py`

## Related ADRs

ADR-0001, ADR-0002, ADR-0004, ADR-0008

## Related capabilities/requirements

CAP-001–CAP-012; REQ-002, REQ-003, REQ-004, REQ-006

## Assumptions

Logical responsibility is more important here than Python package detail.

## Known limitations

This view does not show internal safety gates or deployment topology.

## Review trigger

PolySia assumes a new external responsibility or communicates with a new system.
