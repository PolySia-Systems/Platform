"""Persist reservations before network I/O; restart never refunds uncertainty."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy


class AcquisitionBlockedError(RuntimeError):
    """Stable reason safe to expose in status without provider payloads."""

    def __init__(self, reason: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(reason)
        self.error_code = reason
        self.retry_after_seconds = retry_after_seconds


class AcquisitionAuthority:
    def __init__(self, path: Path, policy: AcquisitionPolicy) -> None:
        self._path = path
        self.policy = policy

    @property
    def evidence_root(self) -> Path:
        return self._path.parent / "evidence"

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS authority (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    policy_digest TEXT NOT NULL, stopped INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    request_id TEXT PRIMARY KEY, endpoint TEXT NOT NULL,
                    reserved_bytes INTEGER NOT NULL, actual_bytes INTEGER,
                    status TEXT NOT NULL, attempted_at TEXT NOT NULL
                );
            """)
            connection.execute(
                "INSERT OR IGNORE INTO authority(singleton, policy_digest) VALUES(1, ?)",
                (self.policy.digest,),
            )
            if connection.execute("SELECT policy_digest FROM authority").fetchone()[0] != (
                self.policy.digest
            ):
                raise AcquisitionBlockedError("authority_policy_changed")

    def reserve(
        self,
        endpoint: str,
        *,
        now: datetime,
        host: str,
        closure: bool = False,
    ) -> str:
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise AcquisitionBlockedError("clock_not_UTC")
        if host != self.policy.host or endpoint not in self.policy.endpoints:
            raise AcquisitionBlockedError("host_or_endpoint_not_authorized")
        if not self.policy.starts_at <= now < self.policy.expires_at:
            raise AcquisitionBlockedError("authority_not_current")
        request_id = uuid.uuid4().hex
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT policy_digest, stopped FROM authority").fetchone()
            if row is None or row[0] != self.policy.digest or row[1]:
                raise AcquisitionBlockedError("authority_stopped_or_mismatched")
            count, charged = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0) "
                "FROM reservations"
            ).fetchone()
            reserve_requests = 0 if closure else self.policy.closure_request_reserve
            reserve_bytes = 0 if closure else self.policy.closure_byte_reserve
            if count >= self.policy.maximum_requests - reserve_requests:
                raise AcquisitionBlockedError("request_budget_exhausted")
            if (
                charged + self.policy.maximum_response_bytes
                > self.policy.maximum_bytes - reserve_bytes
            ):
                raise AcquisitionBlockedError("byte_budget_exhausted")
            window_start = now - timedelta(seconds=self.policy.window_seconds)
            window_count, window_bytes = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0) "
                "FROM reservations WHERE attempted_at>=?",
                (window_start.isoformat(),),
            ).fetchone()
            if window_count >= self.policy.window_maximum_requests:
                raise AcquisitionBlockedError("request_window_exhausted")
            if window_bytes + self.policy.maximum_response_bytes > self.policy.window_maximum_bytes:
                raise AcquisitionBlockedError("byte_window_exhausted")
            connection.execute(
                "INSERT INTO reservations VALUES(?,?,?,NULL,'IN_FLIGHT',?)",
                (request_id, endpoint, self.policy.maximum_response_bytes, now.isoformat()),
            )
        return request_id

    def settle(self, request_id: str, *, response_bytes: int) -> None:
        if (
            type(response_bytes) is not int
            or response_bytes < 0
            or response_bytes > self.policy.maximum_response_bytes
        ):
            raise AcquisitionBlockedError("response_size_outside_reservation")
        with closing(sqlite3.connect(self._path)) as connection, connection:
            changed = connection.execute(
                "UPDATE reservations SET actual_bytes=?, status='COMPLETE' "
                "WHERE request_id=? AND actual_bytes IS NULL",
                (response_bytes, request_id),
            ).rowcount
            if changed != 1:
                raise AcquisitionBlockedError("reservation_unknown_or_already_settled")

    def stop(self) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute("UPDATE authority SET stopped=1 WHERE singleton=1")

    def resume(self, *, now: datetime, host: str) -> None:
        if (
            now.tzinfo is None
            or now.utcoffset() != timedelta(0)
            or host != self.policy.host
            or not self.policy.starts_at <= now < self.policy.expires_at
        ):
            raise AcquisitionBlockedError("authority_not_current")
        with closing(sqlite3.connect(self._path)) as connection, connection:
            changed = connection.execute(
                "UPDATE authority SET stopped=0 WHERE singleton=1 AND policy_digest=?",
                (self.policy.digest,),
            ).rowcount
            if changed != 1:
                raise AcquisitionBlockedError("authority_mismatched")

    def transition_policy(
        self,
        replacement: AcquisitionPolicy,
        *,
        authorization_reference: str,
    ) -> AcquisitionAuthority:
        """Explicit owner-directed continuation; all lifetime charges survive."""
        if not 8 <= len(authorization_reference) <= 128:
            raise AcquisitionBlockedError("explicit_authority_reference_required")
        if replacement.host != self.policy.host or replacement.policy_id == self.policy.policy_id:
            raise AcquisitionBlockedError("replacement_identity_invalid")
        if not set(replacement.endpoints).issubset(self.policy.endpoints):
            raise AcquisitionBlockedError("replacement_cannot_expand_endpoints")
        if replacement.window_seconds < self.policy.window_seconds:
            raise AcquisitionBlockedError("replacement_cannot_shorten_rate_window")
        # These are evidence-retention promises, not expendable request ceilings.
        # Changing either direction needs a separately reviewed storage policy.
        if (replacement.retention_days != self.policy.retention_days
                or replacement.backup_generations != self.policy.backup_generations):
            raise AcquisitionBlockedError("replacement_retention_contract_changed")
        ceilings = (
            "timeout_seconds",
            "backup_generations",
            "maximum_requests",
            "maximum_bytes",
            "maximum_response_bytes",
            "window_maximum_requests",
            "window_maximum_bytes",
            "cohort_limit",
            "memory_max_bytes",
            "cpu_quota_percent",
        )
        if any(getattr(replacement, field) > getattr(self.policy, field) for field in ceilings):
            raise AcquisitionBlockedError("replacement_cannot_raise_ceiling")
        if (
            replacement.minimum_free_disk_bytes < self.policy.minimum_free_disk_bytes
            or replacement.cadence_seconds < self.policy.cadence_seconds
            or replacement.expires_at - replacement.starts_at
            > self.policy.expires_at - self.policy.starts_at
            or replacement.closure_request_reserve < self.policy.closure_request_reserve
            or replacement.closure_byte_reserve < self.policy.closure_byte_reserve
        ):
            raise AcquisitionBlockedError("replacement_cannot_reduce_reserve_or_expand_duration")
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT policy_digest FROM authority").fetchone()
            if old is None or old[0] != self.policy.digest:
                raise AcquisitionBlockedError("replacement_predecessor_mismatched")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS policy_transitions ("
                "old_digest TEXT NOT NULL, new_digest TEXT NOT NULL UNIQUE, "
                "authorization_reference TEXT NOT NULL, old_policy TEXT NOT NULL, "
                "new_policy TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO policy_transitions VALUES(?,?,?,?,?)",
                (
                    self.policy.digest,
                    replacement.digest,
                    authorization_reference,
                    json.dumps(self.policy.to_dict(), sort_keys=True),
                    json.dumps(replacement.to_dict(), sort_keys=True),
                ),
            )
            connection.execute(
                "UPDATE authority SET policy_digest=? WHERE singleton=1", (replacement.digest,)
            )
        return AcquisitionAuthority(self._path, replacement)

    def status(self) -> dict[str, object]:
        with closing(
            sqlite3.connect(f"{self._path.resolve().as_uri()}?mode=ro", uri=True)
        ) as connection:
            authority = connection.execute(
                "SELECT policy_digest, stopped FROM authority"
            ).fetchone()
            count, charged, uncertain = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0),"
                "COALESCE(SUM(actual_bytes IS NULL),0) FROM reservations"
            ).fetchone()
        return {
            "policy_digest": authority[0],
            "stopped": bool(authority[1]),
            "requests_charged": count,
            "bytes_charged": charged,
            "uncertain_requests": uncertain,
        }
