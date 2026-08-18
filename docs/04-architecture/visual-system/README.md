# PolySia Architecture Visual System

This directory is the version-controlled visual architecture layer for PolySia.
It uses C4 semantics for landscape, context, container, and component views and
Mermaid for canonical diagrams-as-code.

## Authority and state

- Baseline Git commit: `449f1c308fc74bd2a541e0e905f281fd19e5cd9b`
- Review date: 2026-08-18
- Architecture model: modular monolith with ports and adapters
- First venue adapter: Polymarket

Every element is classified as `CURRENT`, `TARGET`, `FUTURE`, or `EXTERNAL`.
Target and future elements are not implementation claims.

## Files

- [Diagram index](architecture-visualization-index.md)
- [Design system](architecture-design-system.md)
- [Design tokens](architecture-design-tokens.json)
- [Diagram conventions](diagram-conventions.md)
- [Traceability register](traceability-register.md)
- `sources/`: canonical Mermaid files
- `views/`: GitHub-readable architecture pages
- `rendered/`: optional SVG exports only

Update the Mermaid source and its paired view in the same change. Rendered SVGs
are presentation derivatives and never supersede repository sources.

`python scripts/check_changed_docs.py --architecture-only` checks structural
consistency, coverage, metadata, local paths, and traceability. It does not
replace human review of architectural meaning or rendered visual quality.
