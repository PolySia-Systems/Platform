# Architecture Documentation Instructions

- Scope: `docs/04-architecture/` and descendants.
- Treat a `CURRENT` claim as valid only when verified code, configuration, a
  test, or approved operational evidence supports it.
- Keep each Mermaid source, Markdown view, rendered SVG, diagram-index entry,
  and traceability entry synchronized.
- Update the audited baseline commit and review date when the architecture
  corpus is reviewed against a newer repository revision.
- Label `CURRENT`, `TARGET`, `FUTURE`, and `EXTERNAL` boundaries explicitly;
  use `MIXED` only for a view that deliberately contains multiple statuses.
- Visually inspect every changed diagram after rendering from its canonical
  Mermaid source.
- Do not claim unsupported implementation, deployment, safety, maturity, or
  production readiness.
- Automated structural checks complement, but never replace, human semantic
  and visual review.
