from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from polysia.application.ports.candidate_intelligence import (
    CandidatePipelineBusyError,
    CandidatePipelineLeaseLostError,
)

FAILURE_CATEGORY_SOURCE_UNAVAILABLE = "source_unavailable"
FAILURE_CATEGORY_MARKET_READ_FAILED = "market_read_failed"
FAILURE_CATEGORY_SQLITE_BUSY = "sqlite_busy"
FAILURE_CATEGORY_PERSISTENCE_FAILED = "persistence_failed"
FAILURE_CATEGORY_LEASE_FAILED = "lease_failed"
FAILURE_CATEGORY_UNEXPECTED = "unexpected_internal_failure"

FAILURE_STAGE_ACQUIRE_LEASE = "acquire_lease"
FAILURE_STAGE_COLLECT_EVENTS = "collect_events"
FAILURE_STAGE_MARKET_READ = "market_read"
FAILURE_STAGE_APPLY_EVENTS = "apply_events"
FAILURE_STAGE_RENEW_LEASE = "renew_lease"
FAILURE_STAGE_PERSIST = "persist"
FAILURE_STAGE_FAIL_POLL = "fail_poll"
FAILURE_STAGE_UNEXPECTED = "unexpected"

SANITIZED_FAILURE_CATEGORIES = frozenset(
    {
        FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
        FAILURE_CATEGORY_MARKET_READ_FAILED,
        FAILURE_CATEGORY_SQLITE_BUSY,
        FAILURE_CATEGORY_PERSISTENCE_FAILED,
        FAILURE_CATEGORY_LEASE_FAILED,
        FAILURE_CATEGORY_UNEXPECTED,
    }
)
SANITIZED_FAILURE_STAGES = frozenset(
    {
        FAILURE_STAGE_ACQUIRE_LEASE,
        FAILURE_STAGE_COLLECT_EVENTS,
        FAILURE_STAGE_MARKET_READ,
        FAILURE_STAGE_APPLY_EVENTS,
        FAILURE_STAGE_RENEW_LEASE,
        FAILURE_STAGE_PERSIST,
        FAILURE_STAGE_FAIL_POLL,
        FAILURE_STAGE_UNEXPECTED,
    }
)

_STAGE_SEPARATOR = "__at__"
_TOKEN_PATTERN = re.compile(r"[^a-z0-9_]+")
_WALLET_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}")
_QUERY_PATTERN = re.compile(r"[?&][^=\s]{0,64}=[^&\s]*")
_SQLITE_BUSY_PATTERN = re.compile(r"\b(busy|locked)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ClassifiedContinuousShadowFailure:
    category: str
    stage: str

    @property
    def persistence_code(self) -> str:
        return encode_failure_code(self.category, self.stage)


def sanitize_failure_token(value: str, *, fallback: str) -> str:
    normalized = _TOKEN_PATTERN.sub("_", value.strip().lower()).strip("_")[:80]
    return normalized or fallback


def encode_failure_code(category: str, stage: str) -> str:
    safe_category = sanitize_failure_token(
        category, fallback=FAILURE_CATEGORY_UNEXPECTED
    )
    safe_stage = sanitize_failure_token(stage, fallback=FAILURE_STAGE_UNEXPECTED)
    encoded = f"{safe_category}{_STAGE_SEPARATOR}{safe_stage}"
    return encoded[:80]


def decode_failure_code(value: str | None) -> tuple[str | None, str | None]:
    if value is None or not value.strip():
        return None, None
    raw = value.strip()
    if _STAGE_SEPARATOR in raw:
        category, stage = raw.rsplit(_STAGE_SEPARATOR, 1)
        return (
            sanitize_failure_token(category, fallback=FAILURE_CATEGORY_UNEXPECTED),
            sanitize_failure_token(stage, fallback=FAILURE_STAGE_UNEXPECTED),
        )
    return sanitize_failure_token(raw, fallback=FAILURE_CATEGORY_UNEXPECTED), None


def redact_operator_text(value: str) -> str:
    redacted = _WALLET_PATTERN.sub("0x[redacted]", value)
    return _QUERY_PATTERN.sub("?redacted=[redacted]", redacted)


def classify_continuous_shadow_failure(
    error: BaseException,
    *,
    stage: str,
) -> ClassifiedContinuousShadowFailure:
    safe_stage = (
        stage
        if stage in SANITIZED_FAILURE_STAGES
        else sanitize_failure_token(stage, fallback=FAILURE_STAGE_UNEXPECTED)
    )
    for item in _walk_exceptions(error):
        if _is_sqlite_busy(item):
            return ClassifiedContinuousShadowFailure(
                FAILURE_CATEGORY_SQLITE_BUSY, safe_stage
            )
    for item in _walk_exceptions(error):
        if isinstance(item, (CandidatePipelineBusyError, CandidatePipelineLeaseLostError)):
            return ClassifiedContinuousShadowFailure(
                FAILURE_CATEGORY_LEASE_FAILED, safe_stage
            )
        declared = getattr(item, "error_code", None)
        declared_stage = getattr(item, "processing_stage", None)
        if isinstance(declared, str) and declared in SANITIZED_FAILURE_CATEGORIES:
            resolved_stage = (
                declared_stage
                if isinstance(declared_stage, str)
                and declared_stage in SANITIZED_FAILURE_STAGES
                else safe_stage
            )
            return ClassifiedContinuousShadowFailure(declared, resolved_stage)
        if _is_persistence_error(item):
            return ClassifiedContinuousShadowFailure(
                FAILURE_CATEGORY_PERSISTENCE_FAILED, safe_stage
            )
    return ClassifiedContinuousShadowFailure(FAILURE_CATEGORY_UNEXPECTED, safe_stage)


def _is_persistence_error(error: BaseException) -> bool:
    if isinstance(error, sqlite3.DatabaseError):
        return True
    return any(
        cls.__name__ in {"CandidateStoreError", "ContinuousShadowStoreError"}
        for cls in type(error).__mro__
    )


def _is_sqlite_busy(error: BaseException) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False
    return _SQLITE_BUSY_PATTERN.search(str(error)) is not None


def _walk_exceptions(error: BaseException) -> tuple[BaseException, ...]:
    seen: set[int] = set()
    items: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        items.append(current)
        current = current.__cause__ or current.__context__
    return tuple(items)


__all__ = [
    "ClassifiedContinuousShadowFailure",
    "FAILURE_CATEGORY_LEASE_FAILED",
    "FAILURE_CATEGORY_MARKET_READ_FAILED",
    "FAILURE_CATEGORY_PERSISTENCE_FAILED",
    "FAILURE_CATEGORY_SQLITE_BUSY",
    "FAILURE_CATEGORY_SOURCE_UNAVAILABLE",
    "FAILURE_CATEGORY_UNEXPECTED",
    "FAILURE_STAGE_APPLY_EVENTS",
    "FAILURE_STAGE_COLLECT_EVENTS",
    "FAILURE_STAGE_FAIL_POLL",
    "FAILURE_STAGE_MARKET_READ",
    "FAILURE_STAGE_PERSIST",
    "FAILURE_STAGE_RENEW_LEASE",
    "SANITIZED_FAILURE_CATEGORIES",
    "classify_continuous_shadow_failure",
    "decode_failure_code",
    "encode_failure_code",
    "redact_operator_text",
    "sanitize_failure_token",
]
