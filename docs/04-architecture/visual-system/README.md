# PolySia Architecture Visual System

This directory is the version-controlled visual architecture layer for PolySia.
It uses C4 semantics for landscape, context, container, and component views and
Mermaid for canonical diagrams-as-code.

## Authority and state

- Baseline Git commit: `4f3b611adae17defbcc6e24b4f9f917b466d5ad8`
- Original full-corpus generation baseline: `449f1c308fc74bd2a541e0e905f281fd19e5cd9b`
- Review date: 2026-10-19
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
Each view records its evidence commit and review date. The baseline identifies
the repository state used for the corpus review; unchanged sources retain their
prior semantics.

`python scripts/check_changed_docs.py --architecture-only` checks structural
consistency, coverage, metadata, local paths, and traceability. It does not
replace human review of architectural meaning or rendered visual quality.

The 2026-10-16 review covers the independent Platform delta. Unchanged source
views retain their prior semantics; generalized execution control remains TARGET.
Bounded research Console software is CURRENT, with deployment/usefulness receipts
kept separate in ADR-0021 and the dated execution record.

The 2026-10-19 scoped review updates deployment (13) and trust boundaries (15)
for the fresh private HTTPS installation and independent cold recovery. Other
views retain their earlier reviewed semantics. The dated operational record owns
activation, disabled acquisition, STOP and recovery evidence; runtime queries own
current host truth. Cloudflare remains an optional externally commissioned path.
