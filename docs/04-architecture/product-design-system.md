# PolySia product design system

Status: CURRENT implementation; release and operational commissioning remain separate.
Scope: the existing private PolySia Console. Product language is English/LTR;
RTL/mixed-script fixtures establish bounded layout readiness, not a translation.

## Sources of truth

| Responsibility | Canonical source |
|---|---|
| Palette, semantic themes, typeface, radius and spacing unit | `frontend/src/design/tokens.css` |
| Original selected assets, dimensions and integrity | `frontend/src/assets/` and its `provenance.json` |
| Brand roles | `frontend/src/design/brand.ts` |
| Logo lockup, exact money and evidence badges | `frontend/src/design/Primitives.tsx` |
| Status presentation | `frontend/src/design/status.ts` |
| Page/table/layout recipes | `frontend/src/Console.module.css`, `Workspaces.tsx` |
| Evidence and operation meanings | Python console contracts and their generated TypeScript |
| Shipped bytes | Generated `human_console_assets/manifest.json` |

The architecture-diagram visual system has an independent purpose. Its tokens
remain valid and are not a second Console theme. Historical reference packages
are not application dependencies.

## Visual rules

Use a calm neutral shell, clear headings, readable metadata and restrained brand
red. Light is the default; the theme switch changes presentation within the same
React root and never resets command state. Theme preference is volatile.

Use semantic CSS variables for surfaces, ink, muted text, borders, actions,
focus, success, warning and danger. Keep raw HEX values in tokens.css or original
artwork. Brand red and financial loss/emergency meanings are independent.

Use Inter locally with font-display swap and system fallbacks. Only upright
variable Inter is shipped. Vazirmatn and full localization are FUTURE. Preserve
OFL notices; source bytes are SHA-256 pinned in provenance.json. Cold/failed font
loading must retain usable controls; changing to an arbitrary font may still
require optical adjustments.

Body and controls use 14 px or larger by default; supporting metadata uses 12 px.
Use the existing 8 px spacing unit, restrained 6–8 px corners and logical CSS
properties. Numeric cells and values retain exact string content. Do not reduce
financial text size to make a dense screen fit. Tables have a named keyboard
scroll region, semantic headers and bounded server pagination.

Navigation currently uses visible labels without decorative glyph icons. Add a
licensed consistent icon source only when a real interaction needs it; do not
reintroduce platform-dependent text symbols.

## Brand usage and replacement

BrandLockup owns header placement. It references primary/compact and wordmark
roles, not historical V4/V5 names in pages. Intrinsic artwork: primary 500×472,
compact 459×444; wordmarks 554×196. Use contain, preserve ratios and reserve
explicit width/height. Sidebar artwork always has its intended Midnight surface.
The light-surface wordmark is retained as an approved alternative. Do not invert,
retrace or crop the source artwork to make it fit.

The selected symbol masters are raster; the wordmarks are outlined SVG paths.
The current 32 px favicon is derived from the supplied V5 family. Recognition at
16 px remains limited by the detailed source: no new micro-mark or vector master
is claimed. Later vector delivery is a scoped follow-up, not a reason to hold
all UI work. Validate, update the role map/provenance, rebuild and inspect actual
sizes. Materially changed geometry may require a layout decision.

## Evidence vocabulary

- AVAILABLE: data is structurally published; it does not establish financial
  validity, freshness, completeness or profit.
- EMPTY: the bounded dataset has no rows; it does not prove an empty external account.
- UNKNOWN/UNAVAILABLE/STALE/PARTIAL: communicate the limitation and recovery path;
  never convert these to zero or a healthy green result.
- REQUESTED/CLAIMED: command lifecycle, not observed execution.
- OBSERVED: the owner reported an effect; do not infer profitability.
- FAILED: non-execution is not established. Preserve identity and reconcile.
- MATCHED: reconciliation meaning only, not blanket system readiness.

Status colors use exact mappings, with neutral fallback. Backend enums and action
catalog own semantics/admission. Never add a frontend permission based on color,
label or an optimistic result. Keep amounts as exact strings with explicit units;
do not use Number/parseFloat, invent totals or round financial evidence in UI.
Keep identifiers LTR isolated, and timestamps explicitly UTC. Layout direction
is distinct from language, calendar and financial formatting.

## Adding a page or evidence panel

1. Use a stable internal workspace ID and a display label in messages.ts.
2. Prefer an existing typed workspace response. Do not infer a numeric or financial
   type from generic string cells, and do not edit contract.generated.ts manually.
3. Compose the existing page heading, panel and facts styles. For tables, follow
   the named, keyboard-focusable `tableRegion` recipe in Workspaces.tsx; there is
   no separate TableFrame component. Reuse Amount and Badge rather than creating
   new formatting/status logic.
4. Supply loading, missing, empty, stale, partial and error handling as relevant.
   Show observed time, validity and safe next action; disclosure must not hide a
   critical warning. Reuse the existing synthetic producer fixtures.
5. Review real browser output in both themes, narrow layout and keyboard use.
   Run design guardrails, contracts and the applicable protected browser journeys.

Presentation primitives may import domain types. They must not call the gateway,
authorize operations, or depend on App orchestration. A duplicate component is a
review judgment; static checks do not claim to detect conceptual duplicates.

## State and release behavior

Workspace IDs are independent of English labels. Investigation search/filter
choices live in App memory and survive workspace navigation. Identity/scope
changes reset them. Loaded results, detail and table scroll position are retained in bounded memory
for the same identity, scope, generation and record kind. Navigation restores
that context; generation changes require an explicit refresh. Closing detail
returns focus to the originating record. No navigation state or financial payload is persisted in browser
storage or copied into shareable navigation URLs.

An unsearched list prompts the user to search; it does not claim missing evidence
or a generation change. Editing filters clears the previous results, detail and
cursor before another search. Read failures remain visible across workspace
navigation; they must not restore a previous successful list as the new result.

Changing theme does not remount App or alter preview/intent identity. Existing
bundle mismatch detection blocks incompatible commands, invalidates previews,
keeps an ambiguous intent for exact recovery and never auto-reloads or replays.
A page reload loses volatile navigation; durable authenticated receipts and the
independent protected operator route remain recovery owners.

## Asset custody and maintenance

Use the existing npm build recipe. Vite does not inline images/fonts. The Python
server serves allowlisted exact MIME types as bytes; img/font CSP access is same
origin only. Hash, path, symlink, size, inventory and source-freshness checks remain
fail-closed. Selected media also pass a bounded PNG CRC/data/dimension profile,
WOFF2 header/length profile and a path-only SVG profile. This is not arbitrary
file upload support or a complete font-security engine.

Changing a selected source asset requires updating its provenance hash after
review. The generated manifest is not a substitute for provenance or visual QA.
Do not ship archive/QA/reference ZIPs. No new production dependency was added.

Run `npm test --prefix frontend`, `npm run build --prefix frontend`,
`npm run verify --prefix frontend`, relevant Python tests and protected browser
acceptance. Run repository-required gates for Python/build/security changes.
Existing lab performance budgets in ADR-0024 remain acceptance gates, not
production measurements. Font/image payloads count in review even though JS has
its own budget. Automated axe checks complement rendered review and manual
assistive-technology checks; do not claim WCAG certification.

Replace active consumers before deleting superseded styles. Keep one canonical
Console theme/provider. Restore a complete compatible release through the
protected operator procedure for rollback; do not hot-swap assets during a bound
financial run, downgrade financial stores or renew financial authority. This
change authorizes no deployment or external account mutation.
