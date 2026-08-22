from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from polysia.application.ports.candidate_wallets import (
    CandidateSourceReadError,
    CandidateSourceSchemaError,
    CandidateSourceState,
    CandidateStoredSnapshot,
    CandidateWalletSourcePort,
    CandidateWalletStorePort,
)

Clock = Callable[[], datetime]
_WALLET_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}", re.IGNORECASE)


class CandidateWalletSyncError(RuntimeError):
    """Safe synchronization failure with the last accepted snapshot preserved."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class CandidateHealthLevel(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class CandidateSyncOutcome:
    snapshot: CandidateStoredSnapshot
    idempotent_replay: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_digest": self.snapshot.dataset_digest,
            "idempotent_replay": self.idempotent_replay,
            "record_count": self.snapshot.record_count,
            "run_id": self.snapshot.run_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "source_id": self.snapshot.source_id,
            "source_total_pages": self.snapshot.source_total_pages,
            "status": "succeeded",
            "warning_code": self.snapshot.warning_code,
        }


@dataclass(frozen=True, slots=True)
class CandidateHealthReport:
    source_id: str
    level: CandidateHealthLevel
    checked_at: datetime
    age_seconds: int | None
    warning_after_seconds: int
    critical_after_seconds: int
    reasons: tuple[str, ...]
    state: CandidateSourceState

    @property
    def exit_code(self) -> int:
        return 1 if self.level is CandidateHealthLevel.CRITICAL else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "age_seconds": self.age_seconds,
            "checked_at": self.checked_at.isoformat(),
            "critical_after_seconds": self.critical_after_seconds,
            "current_page_count": self.state.current_page_count,
            "current_record_count": self.state.current_record_count,
            "current_snapshot_id": self.state.current_snapshot_id,
            "last_error_code": self.state.last_error_code,
            "last_run_id": self.state.last_run_id,
            "last_run_status": self.state.last_run_status,
            "last_success_at": None
            if self.state.last_success_at is None
            else self.state.last_success_at.isoformat(),
            "last_warning_code": self.state.last_warning_code,
            "level": self.level.value,
            "reasons": list(self.reasons),
            "source_id": self.source_id,
            "warning_after_seconds": self.warning_after_seconds,
        }


class CandidateWalletSyncService:
    """Coordinates one complete read and one atomic last-known-good promotion."""

    def __init__(
        self,
        source: CandidateWalletSourcePort,
        store: CandidateWalletStorePort,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._source = source
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def sync(
        self,
        *,
        scheduled_for: date,
        force_new: bool = False,
        run_id: str | None = None,
        history_days: int = 365,
        quarantine_days: int = 30,
    ) -> CandidateSyncOutcome:
        if history_days < 30:
            raise ValueError("history_days must be at least 30")
        if quarantine_days < 7:
            raise ValueError("quarantine_days must be at least 7")
        self._store.initialize()
        started_at = self._utc_now()
        start = self._store.start_run(
            self._source.source_id,
            scheduled_for=scheduled_for,
            started_at=started_at,
            force_new=force_new,
            run_id=run_id,
        )
        if start.already_succeeded:
            completed_at = self._utc_now()
            self._prune_history(
                completed_at=completed_at,
                history_days=history_days,
                quarantine_days=quarantine_days,
                failure_message="Snapshot exists, but history retention maintenance failed.",
            )
            return CandidateSyncOutcome(
                snapshot=self._store.stored_snapshot(start.run_id),
                idempotent_replay=True,
            )

        try:
            dataset = await self._source.fetch_snapshot()
            if dataset.source_id != self._source.source_id:
                raise CandidateWalletSyncError(
                    "source_identity_mismatch",
                    "Candidate-wallet source returned a mismatched source id.",
                )
            accepted_at = self._utc_now()
            snapshot = self._store.complete_run(start, dataset, accepted_at=accepted_at)
        except CandidateSourceSchemaError as error:
            sample_gzip, sample_sha256 = _quarantine_sample(error.sample)
            completed_at = self._utc_now()
            self._store.quarantine_run(
                start.run_id,
                reason_code=error.reason_code,
                schema_fingerprint=error.schema_fingerprint,
                sample_gzip=sample_gzip,
                sample_sha256=sample_sha256,
                completed_at=completed_at,
            )
            self._prune_history(
                completed_at=completed_at,
                history_days=history_days,
                quarantine_days=quarantine_days,
                failure_message="Schema quarantine succeeded, but retention maintenance failed.",
            )
            raise CandidateWalletSyncError(
                error.error_code,
                "Candidate-wallet source schema changed; the response was quarantined.",
            ) from error
        except CandidateSourceReadError as error:
            completed_at = self._utc_now()
            safe_message = "Candidate-wallet source read failed after bounded handling."
            self._store.fail_run(
                start.run_id,
                error_code=error.error_code,
                error_message=safe_message,
                completed_at=completed_at,
            )
            self._prune_history(
                completed_at=completed_at,
                history_days=history_days,
                quarantine_days=quarantine_days,
                failure_message="Source failure was recorded, but retention maintenance failed.",
            )
            raise CandidateWalletSyncError(error.error_code, safe_message) from error
        except CandidateWalletSyncError as error:
            completed_at = self._utc_now()
            self._store.fail_run(
                start.run_id,
                error_code=error.error_code,
                error_message=str(error),
                completed_at=completed_at,
            )
            self._prune_history(
                completed_at=completed_at,
                history_days=history_days,
                quarantine_days=quarantine_days,
                failure_message="Ingestion failure was recorded, but retention maintenance failed.",
            )
            raise
        except Exception as error:
            completed_at = self._utc_now()
            self._store.fail_run(
                start.run_id,
                error_code="internal_ingestion_error",
                error_message="Candidate-wallet ingestion failed before atomic promotion.",
                completed_at=completed_at,
            )
            self._prune_history(
                completed_at=completed_at,
                history_days=history_days,
                quarantine_days=quarantine_days,
                failure_message="Ingestion failure was recorded, but retention maintenance failed.",
            )
            raise CandidateWalletSyncError(
                "internal_ingestion_error",
                "Candidate-wallet ingestion failed before atomic promotion.",
            ) from error

        self._prune_history(
            completed_at=accepted_at,
            history_days=history_days,
            quarantine_days=quarantine_days,
            failure_message="Snapshot succeeded, but history retention maintenance failed.",
        )
        return CandidateSyncOutcome(snapshot=snapshot, idempotent_replay=False)

    def health(
        self,
        *,
        warning_after: timedelta = timedelta(hours=36),
        critical_after: timedelta = timedelta(hours=72),
    ) -> CandidateHealthReport:
        if warning_after <= timedelta(0) or critical_after <= warning_after:
            raise ValueError("health thresholds must be positive and increasing")
        self._store.initialize()
        checked_at = self._utc_now()
        state = self._store.source_state(self._source.source_id)
        reasons: list[str] = []
        age_seconds: int | None = None

        if state.last_success_at is None:
            level = CandidateHealthLevel.CRITICAL
            reasons.append("never_succeeded")
            if state.last_run_status is not None:
                reasons.append(f"latest_run_{state.last_run_status}")
        else:
            age = max(timedelta(0), checked_at - state.last_success_at)
            age_seconds = int(age.total_seconds())
            if age > critical_after:
                level = CandidateHealthLevel.CRITICAL
                reasons.append("snapshot_critical_stale")
            elif age > warning_after:
                level = CandidateHealthLevel.WARNING
                reasons.append("snapshot_stale")
            else:
                level = CandidateHealthLevel.HEALTHY

            if state.last_run_status in {"failed", "quarantined"}:
                reasons.append(f"latest_run_{state.last_run_status}")
                if level is CandidateHealthLevel.HEALTHY:
                    level = CandidateHealthLevel.WARNING
            elif state.last_run_status == "running":
                reasons.append("run_in_progress")
                if level is CandidateHealthLevel.HEALTHY:
                    level = CandidateHealthLevel.WARNING
            if state.last_warning_code is not None:
                reasons.append(state.last_warning_code)
                if level is CandidateHealthLevel.HEALTHY:
                    level = CandidateHealthLevel.WARNING

        return CandidateHealthReport(
            source_id=self._source.source_id,
            level=level,
            checked_at=checked_at,
            age_seconds=age_seconds,
            warning_after_seconds=int(warning_after.total_seconds()),
            critical_after_seconds=int(critical_after.total_seconds()),
            reasons=tuple(reasons),
            state=state,
        )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        converted = value.astimezone(UTC)
        if value.utcoffset() != timedelta(0):
            raise ValueError("clock must return UTC")
        return converted

    def _prune_history(
        self,
        *,
        completed_at: datetime,
        history_days: int,
        quarantine_days: int,
        failure_message: str,
    ) -> None:
        try:
            self._store.prune_history(
                snapshot_cutoff=completed_at - timedelta(days=history_days),
                quarantine_cutoff=completed_at - timedelta(days=quarantine_days),
            )
        except Exception as error:
            raise CandidateWalletSyncError(
                "history_prune_failed",
                failure_message,
            ) from error


def _quarantine_sample(sample: object) -> tuple[bytes, str]:
    redacted = _redact_sample(sample)
    encoded = json.dumps(
        redacted,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 128_000:
        encoded = json.dumps(
            {
                "sample_truncated": True,
                "top_level_type": type(sample).__name__,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    if len(compressed) > 65_536:
        encoded = json.dumps(
            {
                "sample_omitted": True,
                "top_level_type": type(sample).__name__,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    return compressed, hashlib.sha256(compressed).hexdigest()


def _redact_sample(value: object, *, depth: int = 0) -> object:
    if depth >= 6:
        return "<depth-limited>"
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 50:
                redacted["<remaining-fields>"] = len(value) - index
                break
            raw_key = str(key)
            safe_key = _WALLET_PATTERN.sub("<wallet-redacted>", raw_key)
            if safe_key != raw_key:
                safe_key = f"{safe_key}-{index}"
            if safe_key.lower() in {"address", "wallet", "wallet_address"}:
                redacted[safe_key] = "<wallet-redacted>"
            elif safe_key == "data" and isinstance(item, list):
                redacted[safe_key] = [
                    _redact_sample(entry, depth=depth + 1) for entry in item[:3]
                ]
                if len(item) > 3:
                    redacted["data_omitted_count"] = len(item) - 3
            else:
                redacted[safe_key] = _redact_sample(item, depth=depth + 1)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_sample(item, depth=depth + 1) for item in value[:10]]
    if isinstance(value, str):
        return _WALLET_PATTERN.sub("<wallet-redacted>", value)
    if value is None or isinstance(value, (bool, int, str, Decimal)):
        return value
    return f"<{type(value).__name__}>"


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
