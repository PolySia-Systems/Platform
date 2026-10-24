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

## 2026-10-25 bounded validation-policy amendment

CURRENT: the packet adds the shared versioned policy projection, including source
and policy identity, actual paths, contexts, reasons and fallback diagnostics.
Requested document scope unions with actual validation paths and cannot narrow
them. Both rename sides, deletions and local staged/unstaged/untracked paths are
retained. Policy/source identity joins cache invalidation; dirty-cache refusal and
task/safety trust boundaries remain. Catalog renders the policy instead of owning
an applicability table. Recommendations, verified evidence, stale/failed evidence
and unknown/unavailable evidence remain distinct. This offline packet does not
verify native CI and creates no evidence-fetching service or cross-commit cache.
The [validation contract](../../03-requirements/developer-context-packet.md#validation-policy-and-local-preflight)
owns the detailed behavior. Rollback reverts the complete validation-efficiency
merge, preserving consumer/CI policy parity.

## Consequences of the original decision

Ordinary resume remains the Issue or PR. `docs/README.md` remains the
documentation entrance. Validation scope stays owned by
`scripts/classify_ci_changes.py`. Rollback is revert of this ADR and the
developer tooling modules.
