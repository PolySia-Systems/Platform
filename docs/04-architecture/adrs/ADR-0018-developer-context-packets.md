# ADR-0018: Developer Context Packets Are Disposable Views

- Status: Accepted
- Date: 2026-09-20

## Context

Coding agents resume work from Issues, PRs, code, tests, and approved
documents. Chat history is not an authority. A generated briefing that is
mistaken for a maintained knowledge base would duplicate truth and drift from
Git, requirements, and ADRs.

## Decision

Add a local, non-trading developer command that builds a bounded context
packet from repository identity, the AGENTS instruction chain, scoped
requirements/ADRs, and the existing CI change classifier. Packets are
generated views. They MUST NOT become a second source of truth, a workflow
engine, or a production control plane.

Safety instructions from root `AGENTS.md` are retained even when non-safety
excerpts are dropped for size. Untrusted task text is never copied into the
packet or rendered output. `next_action` may interpolate only a sanitized
opaque Issue/PR identifier. Secret files are out of scope.

Cache identity includes the sanitized task reference. Dirty worktrees never
reuse or publish a cached packet; their file contents can change while Git's
porcelain path list remains the same.

## Consequences

Ordinary resume remains the Issue or PR. `docs/README.md` remains the
documentation entrance. Validation scope stays owned by
`scripts/classify_ci_changes.py`. Rollback is revert of this ADR and the
developer tooling modules.
