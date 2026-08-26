from __future__ import annotations

import sqlite3

from polysia.application.ports.candidate_intelligence import CandidatePipelineBusyError
from polysia.application.services.continuous_shadow import ContinuousShadowError
from polysia.application.services.continuous_shadow_failures import (
    FAILURE_CATEGORY_LEASE_FAILED,
    FAILURE_CATEGORY_MARKET_READ_FAILED,
    FAILURE_CATEGORY_PERSISTENCE_FAILED,
    FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
    FAILURE_CATEGORY_SQLITE_BUSY,
    FAILURE_CATEGORY_UNEXPECTED,
    FAILURE_STAGE_COLLECT_EVENTS,
    FAILURE_STAGE_MARKET_READ,
    FAILURE_STAGE_PERSIST,
    classify_continuous_shadow_failure,
    decode_failure_code,
    encode_failure_code,
    redact_operator_text,
)


def test_classify_distinguishes_sanitized_failure_categories() -> None:
    source = ContinuousShadowError(
        "Leader source was unavailable.",
        error_code=FAILURE_CATEGORY_SOURCE_UNAVAILABLE,
        processing_stage=FAILURE_STAGE_COLLECT_EVENTS,
    )
    market = ContinuousShadowError(
        "Market metadata was unavailable.",
        error_code=FAILURE_CATEGORY_MARKET_READ_FAILED,
        processing_stage=FAILURE_STAGE_MARKET_READ,
    )
    busy = sqlite3.OperationalError("database is locked")
    persist = sqlite3.DatabaseError("disk I/O error")
    lease = CandidatePipelineBusyError("lease owned")
    unexpected = RuntimeError("safe internal failure")

    assert classify_continuous_shadow_failure(
        source, stage=FAILURE_STAGE_COLLECT_EVENTS
    ).category == FAILURE_CATEGORY_SOURCE_UNAVAILABLE
    assert classify_continuous_shadow_failure(
        market, stage=FAILURE_STAGE_MARKET_READ
    ).category == FAILURE_CATEGORY_MARKET_READ_FAILED
    assert (
        classify_continuous_shadow_failure(busy, stage=FAILURE_STAGE_PERSIST).category
        == FAILURE_CATEGORY_SQLITE_BUSY
    )
    assert (
        classify_continuous_shadow_failure(persist, stage=FAILURE_STAGE_PERSIST).category
        == FAILURE_CATEGORY_PERSISTENCE_FAILED
    )
    assert (
        classify_continuous_shadow_failure(lease, stage="renew_lease").category
        == FAILURE_CATEGORY_LEASE_FAILED
    )
    assert (
        classify_continuous_shadow_failure(unexpected, stage=FAILURE_STAGE_PERSIST).category
        == FAILURE_CATEGORY_UNEXPECTED
    )


def test_sqlite_busy_in_cause_chain_is_not_masked_by_wrapper() -> None:
    busy = sqlite3.OperationalError("database is locked")
    wrapped = ContinuousShadowError("wrapper")
    wrapped.__cause__ = busy
    classified = classify_continuous_shadow_failure(wrapped, stage=FAILURE_STAGE_PERSIST)
    assert classified.category == FAILURE_CATEGORY_SQLITE_BUSY
    assert classified.stage == FAILURE_STAGE_PERSIST


def test_encode_decode_round_trip_and_address_redaction() -> None:
    encoded = encode_failure_code(
        FAILURE_CATEGORY_SOURCE_UNAVAILABLE, FAILURE_STAGE_COLLECT_EVENTS
    )
    category, stage = decode_failure_code(encoded)
    assert category == FAILURE_CATEGORY_SOURCE_UNAVAILABLE
    assert stage == FAILURE_STAGE_COLLECT_EVENTS
    address = "0x" + "a" * 40
    redacted = redact_operator_text(
        f"failed for {address} at https://example.test/path?key=secret"
    )
    assert address not in redacted
    assert "secret" not in redacted
    assert "0x[redacted]" in redacted
