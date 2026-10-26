"""Native process identity for protected local operator grants; no actor flag."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any

from polysia.domain.financial_session import SessionBlocked


def native_actor() -> str:
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(257)
        length = ctypes.c_ulong(len(buffer))
        if not ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(length)):
            raise SessionBlocked("native_operator_identity_unavailable")
        return buffer.value
    import pwd

    return pwd.getpwuid(os.geteuid()).pw_name


def local_scope(registry: Path) -> tuple[str, str, frozenset[str]]:
    import json

    if registry.is_symlink() or registry.stat().st_size > 65536:
        raise SessionBlocked("bounded_local_operator_registry_required")
    record: dict[str, Any] = json.loads(registry.read_text(encoding="utf-8"))
    actor = native_actor()
    if (
        record.get("version") != "scoped-operator-registry/v1"
        or record.get("host") != socket.gethostname()
    ):
        raise SessionBlocked("local_operator_registry_host_mismatch")
    role = record.get("roles", {}).get(actor)
    if role != "operator":
        raise SessionBlocked("trusted_native_operator_required")
    return actor, role, frozenset(record["targets"])
