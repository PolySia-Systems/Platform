# PolySia Architecture Visual System

This directory is the version-controlled visual architecture layer for PolySia.
It uses C4 semantics for landscape, context, container, and component views and
Mermaid for canonical diagrams-as-code.

## Authority and state

- Baseline Git commit: `44a8ae0fbccd0de916a0621236ea5931e7c3a256`
- Review date: 2026-07-11
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
- [Figma/FigJam handoff](figma-handoff-spec.md)
- `sources/`: canonical Mermaid files
- `views/`: GitHub-readable architecture pages
- `rendered/`: optional SVG exports only

Update the Mermaid source and its paired view in the same change. Figma is a
presentation derivative and never supersedes repository sources.
