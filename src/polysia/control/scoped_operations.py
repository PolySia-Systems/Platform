"""Typed allowlisted operations, distinct from legacy Shadow acquisition commands."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from polysia.domain.financial_session import digest, utc

Operation = Literal[
    "shadow.create",
    "shadow.clone",
    "shadow.start",
    "shadow.drain",
    "shadow.resume",
    "shadow.finalize",
    "shadow.archive",
    "shadow.compare",
    "policy.stage",
    "session.stop",
    "session.drain",
]
OPERATIONS = frozenset(
    {
        "shadow.create",
        "shadow.clone",
        "shadow.start",
        "shadow.drain",
        "shadow.resume",
        "shadow.finalize",
        "shadow.archive",
        "shadow.compare",
        "policy.stage",
        "session.stop",
        "session.drain",
    }
)


@dataclass(frozen=True, slots=True)
class ScopedPreview:
    operation: Operation
    target: str
    expected_revision: int
    actor: str
    created_at: datetime
    expires_at: datetime
    arguments: tuple[tuple[str, str], ...] = ()
    version: str = "scoped-operation/v1"

    def __post_init__(self) -> None:
        if (
            self.operation not in OPERATIONS
            or self.version != "scoped-operation/v1"
            or re.fullmatch(r"[A-Za-z0-9._:@/-]{1,128}", self.target) is None
            or not self.actor
            or type(self.expected_revision) is not int
            or self.expected_revision < 0
            or not 0 < (utc(self.expires_at) - utc(self.created_at)).total_seconds() <= 300
        ):
            raise ValueError("invalid scoped operation preview")
        fields = dict(self.arguments)
        reserved = self.target.endswith((":stop", ":drain"))
        expected_suffix = {"session.stop": ":stop", "session.drain": ":drain"}.get(self.operation)
        if (expected_suffix is not None and not self.target.endswith(expected_suffix)) or (
            expected_suffix is None and reserved
        ):
            raise ValueError("operation_target_kind_mismatch")
        allowed = {
            "shadow.clone": {"source"},
            "shadow.compare": {"other"},
            "policy.stage": {"policy_digest"},
            "shadow.create": {"policy_digest"},
        }
        required = allowed.get(self.operation, set())
        optional = {"source_policy_digest"} if self.operation == "shadow.clone" else set()
        if (
            not required <= set(fields)
            or set(fields) - required - optional
            or len(fields) != len(self.arguments)
        ):
            raise ValueError("operation arguments are not allowlisted")
        if (
            "source_policy_digest" in fields
            and re.fullmatch(r"[a-f0-9]{64}", fields["source_policy_digest"]) is None
        ):
            raise ValueError("clone_policy_digest_invalid")
        if any(
            re.fullmatch(r"[A-Za-z0-9._:@/-]{1,128}", value) is None for value in fields.values()
        ):
            raise ValueError("operation target or policy identity invalid")

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))
