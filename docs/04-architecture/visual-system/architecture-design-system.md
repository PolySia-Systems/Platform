# PolySia Architecture Design System

## Signature

The visual language is minimal, calm, technical, and premium. It favors
whitespace, alignment, accessible contrast, explicit status, and short labels.
It uses no gradients, decorative shadows, or ornamental infrastructure.

## Typography

- Inter: titles, component names, descriptions, and annotations.
- JetBrains Mono: paths, ports, events, commands, states, and identifiers.

## Status semantics

| Status | Treatment | Meaning |
|---|---|---|
| CURRENT | Solid border, white fill | Implemented and traceable to repository evidence |
| TARGET | Dashed border, light fill | Approved evolution, not fully implemented |
| FUTURE | Dotted border, muted fill | Optional later capability, not a commitment |
| EXTERNAL | Gray treatment | Outside PolySia ownership |
| SAFETY | Amber accent | Independent risk or operational safety control |
| EMERGENCY | Red accent | Stop, rejection, lockout, or safety pause |
| HEALTHY | Green accent | Approved or healthy transition |

## Flow semantics

- Solid arrow: synchronous command or call.
- Dashed arrow: event or asynchronous data flow.
- Labeled heavy arrow: persistent state update.
- Red labeled arrow: rejection, pause, or emergency stop.
- Green labeled arrow: approval or healthy promotion.
- Gray dashed arrow: optional or future integration.

## Layout

Use an 8 px base unit, 24 px component gaps, 32 px group padding, 12 px
component radii, and 1.5 px standard strokes. Operational views flow left to
right; hierarchy flows top to bottom. Keep each view to seven plus or minus two
primary groups and use progressive disclosure instead of a wall of boxes.

The machine-readable values are in
[`architecture-design-tokens.json`](architecture-design-tokens.json).
