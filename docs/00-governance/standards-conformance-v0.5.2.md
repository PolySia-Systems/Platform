# Standards v0.5.2 consumer adoption review

Date: 2026-10-16. Consumer: `PolySia-Systems/Platform` only.

Decision: adopt immutable Standards v0.5.2 at
`2ccbe4dbbcb3574db52e5a8eb73e968a9165a83c`, release 414090521,
selecting exactly `PRF-BASE` and `PRF-PYS`. The owner authorized this adoption
through the 16 October Platform execution request. The original Standards
repository and its visibility are unchanged.

The selected profile/framework/Python requirement prose is unchanged from
v0.4.0 except a non-normative clarification that each consumer owns its pin.
v0.5.2 adds machine-readable source metadata and optional tooling; optional
Golden Path 2, unselected profiles, Draft requirements and private tooling are
not implicitly adopted. Selected Core requirements are reviewed against the
exact released source before retaining their consumer classifications.

The resolved 114 requirement identities, 89 applicable consumer requirements,
15 absent-event conditions and 10 source-authority responsibilities remain in
`standards/adoption.toml` and `standards/conformance.toml`. Consumer evidence,
full-tree local enforcement, locked dependencies, package checks and stronger
trading-safety rules remain mandatory. No grandfathering or exception is added.

Normal CI validates local consumer records without private repository access.
Validation is recorded in the execution PR and execution record; this review
does not certify future engineering changes or a deployment.

Rollback: revert the adoption, conformance, validator and guidance changes
together. Keep the earlier dated reviews as historical evidence.
