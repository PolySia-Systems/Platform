# PolySia Operating Charter

Version: 1.1. Status: CURRENT. Reviewed: 2026-11-16.

## Purpose

Build a reliable, risk-controlled trading and prediction-market platform through
small, useful, verifiable changes. Polymarket is the first adapter. The current
system is a Python modular monolith. Future markets and capabilities are options,
not prerequisites for ordinary development. Preserve working behavior and prefer
less recurring complexity when value and safety are equivalent.

## Governing sources

[Root instructions](../../AGENTS.md) own universal operating rules, fact ownership,
precedence, safety and completion policy. Applicable nested guides add local rules.
[Document control](document-control.md) identifies durable sources. Adopted
Standards retain exactly their recorded applicability, requirement semantics and
exception rules; this charter neither expands nor weakens that adoption.

Approved requirements and ADRs remain binding in scope. Material architecture
changes require an ADR/RFC and measured need. Historical roadmaps and future
taxonomy do not establish implemented behavior or mandatory delivery scope.

## Delivery principles

- Begin with the actual user outcome and smallest relevant source set.
- Independent Risk, execution boundaries, reconciliation, emergency control,
  Decimal accounting and durable recovery remain mandatory under root safety.
- Prove behavior with applicable tests and exact-revision evidence. Old pass
  counts, preparation and skipped checks are not current verification.
  Host state requires a host query.
- Keep credentials private. Each state-changing external run requires specific
  owner authority; routine development and test success do not supply it.
- Delete or consolidate where purpose and consumers justify it. Preserve
  necessary contracts, history and recovery. Avoid speculative infrastructure.
- Use proportional validation and concise Issue/PR continuity. Explain changes,
  actual evidence, limits and rollback without mandatory elaborate packets.

## Historical startup charter

The original 2026-07-11 charter is preserved immutably in
[Git at 4f0a596](https://github.com/PolySia-Systems/Platform/blob/4f0a596b598d65c50fc1a44e531f11b0ffb7e186/docs/00-governance/master-operating-charter.md).
It records startup discovery, possible markets, future architecture and templates.
Its initial questionnaires, sixteen-part prompt template, `prompts/` directory
and universal handoff format are retired as routine execution requirements.
Historical context does not override current guidance. Selected Standards,
approved decisions/requirements and necessary safety rules remain in their owners.

This consolidation does not authorize a financial action, deployment,
infrastructure migration or compatibility break.
