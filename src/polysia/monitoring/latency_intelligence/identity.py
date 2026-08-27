"""Runtime identity for observational telemetry. Missing values are UNKNOWN."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from polysia.monitoring.latency_intelligence.contract import RuntimeIdentity
from polysia.monitoring.latency_intelligence.policy import (
    CONFIGURATION_VERSION,
    PERFORMANCE_POLICY_VERSION,
    UNKNOWN,
)

_BUILD_COMMIT_PATHS = (
    Path("/opt/polysia/BUILD_COMMIT"),
    Path("BUILD_COMMIT"),
)


def load_runtime_identity(*, venue_id: str | None = None) -> RuntimeIdentity:
    return RuntimeIdentity(
        host_id=_env("POLYSIA_HOST_ID") or _env("HOSTNAME") or UNKNOWN,
        provider=_env("POLYSIA_PROVIDER"),
        region=_env("POLYSIA_REGION"),
        deploy_sha=_deploy_sha(),
        runtime_version=platform.python_version() or UNKNOWN,
        image_digest=_env("POLYSIA_IMAGE_DIGEST") or _env("POLYSIA_IMAGE_TAG"),
        configuration_version=_env("POLYSIA_CONFIGURATION_VERSION") or CONFIGURATION_VERSION,
        policy_version=_env("POLYSIA_LATENCY_POLICY_VERSION") or PERFORMANCE_POLICY_VERSION,
        venue_id=_token(venue_id) if venue_id else _env("POLYSIA_VENUE_ID"),
    ).sanitized()


def telemetry_enabled() -> bool:
    raw = os.environ.get("POLYSIA_LATENCY_TELEMETRY_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def probes_enabled() -> bool:
    raw = os.environ.get("POLYSIA_LATENCY_PROBE_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _deploy_sha() -> str:
    for name in ("POLYSIA_BUILD_COMMIT", "POLYSIA_IMAGE_TAG", "GIT_COMMIT"):
        value = _env(name)
        if value != UNKNOWN:
            return value
    for path in _BUILD_COMMIT_PATHS:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return _token(text)
    return UNKNOWN


def _env(name: str) -> str:
    return _token(os.environ.get(name))


def _token(value: str | None) -> str:
    text = "" if value is None else value.strip()
    return text if text else UNKNOWN
