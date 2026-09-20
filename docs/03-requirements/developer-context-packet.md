# Developer Context Packet

- **Status:** CURRENT
- **Mode:** local developer tooling
- **No authority:** no Live, Risk, Execution, wallet, order, or host-control path

Produce a bounded, deterministic context packet so a model without chat
history can resume one scoped repository task from repository truth.

## Required behavior

The Issue or PR remains the ordinary task owner. [`docs/README.md`](../README.md)
remains the canonical documentation entrance. Generated packets are disposable
views and are never project truth.

A packet MUST report:

- repository identity, exact HEAD, and dirty-state fingerprint;
- an opaque Issue/PR identifier when a task reference is supplied;
- applicable `AGENTS.md` files discovered from the repository root toward the
  scoped path;
- relevant requirements and approved ADRs with path, digest, and why they apply;
- implementation boundaries and existing capabilities to reuse;
- validation scope derived from `scripts/classify_ci_changes.py`;
- reusable validation evidence and checks still missing;
- unresolved decisions and the next concrete action.

Task input is untrusted data. The packet and rendered text MUST contain only a
sanitized opaque identifier such as `PR #123`, or an omission marker. Raw task
text MUST NOT appear in JSON, excerpts, `next_action`, or human-readable output.
The tool MUST NOT read secret files, execute Issue/PR/log text, or silently
omit safety instructions when excerpts are truncated. Cache reuse is valid only
when HEAD, dirty fingerprint, instruction digest, scope, and environment
fingerprints match.

Dependency-classified changes include both configured supply-chain gates:
`python -m pip_audit --strict --vulnerability-service osv` and
`cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json`.

## Command

```text
python -m polysia.cli system developer-context \
  --task <issue-or-pr-reference> \
  --scope <path> \
  --json-file artifacts/developer-context.json
```

Human-readable text is the default stdout. JSON is versioned as
`developer-context-packet-v1`.
