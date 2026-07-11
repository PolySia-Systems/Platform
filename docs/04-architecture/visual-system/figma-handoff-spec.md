# Figma / FigJam Handoff Specification

## Principle

Mermaid and Markdown in the repository are authoritative. Figma/FigJam is a
polished presentation derivative. Update it only after repository diagrams are
approved.

## Pages

| Page | Content |
|---|---|
| 00 — Cover | Product identity, baseline commit, review date, status legend |
| 01 — Design System | Tokens, typography, flow semantics, reusable components |
| 02 — System Landscape | PSA-ARCH-01 |
| 03 — C4 Context | PSA-ARCH-02 |
| 04 — Current Architecture | PSA-ARCH-03 and PSA-ARCH-05 |
| 05 — Target Architecture | PSA-ARCH-04 and PSA-ARCH-17 |
| 06 — Multi-Strategy | PSA-ARCH-06 |
| 07 — Core Flows | PSA-ARCH-07, PSA-ARCH-08, PSA-ARCH-09 |
| 08 — Risk & Safety | PSA-ARCH-10 and PSA-ARCH-12 |
| 09 — Reconciliation | PSA-ARCH-11 |
| 10 — Deployment & Trust | PSA-ARCH-13, PSA-ARCH-14, PSA-ARCH-15, PSA-ARCH-16 |
| 11 — Roadmap | PSA-ARCH-18 |
| 99 — Archive | Superseded exports with source commit and date |

## Reusable components

- `Architecture/Component/Current`
- `Architecture/Component/Target`
- `Architecture/Component/Future`
- `Architecture/ExternalSystem`
- `Architecture/Database`
- `Architecture/Actor`
- `Architecture/Adapter`
- `Architecture/SafetyControl`
- `Architecture/EmergencyControl`
- `Flow/Command`
- `Flow/Event`
- `Flow/StateUpdate`
- `Flow/Emergency`
- `Badge/Current`
- `Badge/Target`
- `Badge/Future`
- `Legend/Architecture`
- `Frame/Metadata`

Build components with Auto Layout, 8 px increments, token colors, 12 px radius,
and a 1.5 px default stroke. Expose status, domain color, icon visibility, label,
description, and path as properties where appropriate.

## Frame metadata

Every frame must display:

- diagram title and ID;
- scope;
- current Git commit;
- architecture status;
- last reviewed date;
- source Mermaid file;
- related ADRs;
- related capabilities;
- owner.

Use baseline commit `44a8ae0fbccd0de916a0621236ea5931e7c3a256` for this pack.

## Transfer method

1. Validate the canonical Mermaid source.
2. Export SVG only with an available external/documentation renderer.
3. Import SVG into Figma/FigJam as a reference layer.
4. Rebuild only high-value presentation frames with reusable components.
5. Compare labels, arrows, statuses, and legends against the paired Markdown view.
6. Record the repository commit in frame metadata.
7. Archive superseded frames; never silently overwrite provenance.

Recommended high-value rebuild order: multi-strategy, risk/emergency, current
container, context, and roadmap. Other views may remain imported SVGs.

## Review checklist

- CURRENT, TARGET, FUTURE, and EXTERNAL treatments match tokens.
- No Strategy-to-Venue connection exists.
- Emergency control is independent and visually dominant.
- Current deployment shows no cloud/VPS/container claim.
- All source paths and statuses match the repository view.
- Figma contains no credentials, wallet identifiers, account data, or token IDs.
