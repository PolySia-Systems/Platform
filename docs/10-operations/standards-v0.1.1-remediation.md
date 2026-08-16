# Standards v0.1.1 Remediation

## Scope

This migration resolves the ten findings recorded by the temporary Standards
baseline. It does not change trading behavior, risk controls, credentials,
deployment state, or any live system.

## Compatibility mappings

Repository-owned `APP_ENV` values now use `development` or `production`.
`AppSettings` continues to accept the earlier `local` and `server` inputs, plus
the documented short aliases, and normalizes them at the configuration boundary.

Maintainer utility paths changed from hyphenated names to Python snake case:

| Previous path | Current path |
|---|---|
| `scripts/build-copy-signal-arbiter-replay-input.py` | `scripts/build_copy_signal_arbiter_replay_input.py` |
| `scripts/check-secrets.py` | `scripts/check_secrets.py` |
| `scripts/copy-signal-arbiter-replay.py` | `scripts/copy_signal_arbiter_replay.py` |
| `scripts/copytrading-stage1.py` | `scripts/copytrading_stage1.py` |

The internal module `polysia.config.logging` moved to
`polysia.config.structured_logging` to avoid colliding with the Python standard
library. All repository-owned imports changed atomically. Neither module is a
documented public API.

## Rollback

Revert the remediation commit to restore the earlier names and example values.
Do not remove the legacy `APP_ENV` input mapping independently until deployed
consumers have been verified to use canonical values.
