# ADR-0010: Documentation Architecture and Legacy Archive

- Status: Accepted
- Date: 2026-07-11

## Context

Legacy phase documents contain useful evidence but stale counts, branches, and
status. The charter names `docs/18-ai-handoffs`; the execution prompt explicitly
requires Phase A under `docs/13-ai-handoffs`.

## Decision

Archive phase-history documents under `docs/99-archive/legacy-phase-docs`
without rewriting them. Keep current operator runbooks at stable paths until
versioned replacements exist. Preserve the required Phase A files under
`docs/13-ai-handoffs`; use `docs/18-ai-handoffs` for future canonical handoffs
because the charter has higher authority.

## Consequences

Primary navigation points to controlled current documents. Historical claims
remain visible but non-authoritative. Links, tests, and operator paths must be
validated before any later move or deletion.

