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

    def __init__(self, reason: str, *, retry_after_seconds: int | None = None,
                 retry_at: datetime | None = None) -> None:
        super().__init__(reason)
        self.error_code = reason
        self.retry_after_seconds = retry_after_seconds
        self.retry_at = retry_at


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
                CREATE INDEX IF NOT EXISTS reservation_time ON reservations(attempted_at);
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
            latest = connection.execute("SELECT MAX(attempted_at) FROM reservations").fetchone()[0]
            if latest and datetime.fromisoformat(latest) > now:
                raise AcquisitionBlockedError("acquisition_clock_regressed")
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
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='finite_campaign_grants'"
            ).fetchone():
                grant = connection.execute(
                    "SELECT baseline_rowid,additional_requests,additional_bytes "
                    "FROM finite_campaign_grants"
                ).fetchone()
                if grant:
                    new_count, new_bytes = connection.execute(
                        "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0) "
                        "FROM reservations WHERE rowid>?", (grant[0],),
                    ).fetchone()
                    if new_count >= grant[1] - reserve_requests:
                        raise AcquisitionBlockedError("request_budget_exhausted")
                    if new_bytes + self.policy.maximum_response_bytes > grant[2] - reserve_bytes:
                        raise AcquisitionBlockedError("byte_budget_exhausted")
            window_start = now - timedelta(seconds=self.policy.window_seconds)
            window_count, window_bytes = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0) "
                "FROM reservations WHERE attempted_at>=?",
                (window_start.isoformat(),),
            ).fetchone()
            if window_count >= self.policy.window_maximum_requests:
                raise AcquisitionBlockedError("request_window_exhausted", retry_at=self._retry_at(
                    connection, now=now,
                ))
            if window_bytes + self.policy.maximum_response_bytes > self.policy.window_maximum_bytes:
                raise AcquisitionBlockedError("byte_window_exhausted", retry_at=self._retry_at(
                    connection, now=now,
                ))
            connection.execute(
                "INSERT INTO reservations VALUES(?,?,?,NULL,'IN_FLIGHT',?)",
                (request_id, endpoint, self.policy.maximum_response_bytes, now.isoformat()),
            )
        return request_id

    def _retry_at(self, connection: sqlite3.Connection, *, now: datetime) -> datetime | None:
        """First provably fitting instant for both inclusive rolling constraints.

        Unsettled reads retain their full charge. A scheduler may recheck once per
        cadence for settlement; this timestamp never promises authority past expiry.
        This runs under the same reservation lock as the actual admission check.
        """
        rows = connection.execute(
            "SELECT attempted_at,COALESCE(actual_bytes,reserved_bytes) FROM reservations "
            "WHERE attempted_at>=? ORDER BY attempted_at",
            ((now - timedelta(seconds=self.policy.window_seconds)).isoformat(),),
        ).fetchall()
        count, charged = len(rows), sum(row[1] for row in rows)
        candidate = now
        index = 0
        while (count >= self.policy.window_maximum_requests or
               charged + self.policy.maximum_response_bytes > self.policy.window_maximum_bytes):
            if index == len(rows):
                return None  # Even an empty window cannot fit this enforced response bound.
            stamp = rows[index][0]
            candidate = datetime.fromisoformat(stamp) + timedelta(
                seconds=self.policy.window_seconds, microseconds=1,
            )
            while index < len(rows) and rows[index][0] == stamp:
                charged -= rows[index][1]
                count -= 1
                index += 1
        return candidate if candidate < self.policy.expires_at else None

    def window_retry_at(self, *, now: datetime) -> datetime | None:
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise AcquisitionBlockedError("clock_not_UTC")
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._retry_at(connection, now=now)

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
        authorized_new_endpoints: tuple[str, ...] = (),
    ) -> AcquisitionAuthority:
        """Explicit owner-directed continuation; all lifetime charges survive."""
        if not 8 <= len(authorization_reference) <= 128:
            raise AcquisitionBlockedError("explicit_authority_reference_required")
        if replacement.host != self.policy.host or replacement.policy_id == self.policy.policy_id:
            raise AcquisitionBlockedError("replacement_identity_invalid")
        additions = set(replacement.endpoints) - set(self.policy.endpoints)
        if additions and additions != set(authorized_new_endpoints):
            raise AcquisitionBlockedError("replacement_cannot_expand_endpoints")
        if (
            len(set(authorized_new_endpoints)) != len(authorized_new_endpoints)
            or set(authorized_new_endpoints) != additions
        ):
            raise AcquisitionBlockedError("explicit_exact_new_endpoint_authority_required")
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

    def grant_finite_campaign(
        self, replacement: AcquisitionPolicy, *, now: datetime,
        authorization_reference: str, additional_requests: int, additional_bytes: int,
    ) -> AcquisitionAuthority:
        """Explicit new nonfinancial grant, separate from restrictive continuation.

        Historical consumption stays charged. The new policy expresses cumulative
        absolute limits; a durable journal binds the exact additional allowance.
        There is no automatic renewal, refund or financial capability.
        """
        allowed = {
            "https://data-api.polymarket.com/v2/activity",
            "https://data-api.polymarket.com/v2/trades",
            "https://data-api.polymarket.com/v2/positions",
            "https://data-api.polymarket.com/positions",
            "https://data-api.polymarket.com/closed-positions",
            "https://gamma-api.polymarket.com/events",
            "https://gamma-api.polymarket.com/markets",
            "https://clob.polymarket.com/book",
            "https://polycop.fun/api/leaderboard",
        }
        if (now.tzinfo is None or now.utcoffset() != timedelta(0)
                or not 8 <= len(authorization_reference) <= 128
                or replacement.policy_id == self.policy.policy_id
                or replacement.host != self.policy.host
                or not now <= replacement.starts_at < replacement.expires_at
                or replacement.expires_at - replacement.starts_at > timedelta(hours=72)
                or type(additional_requests) is not int or not 1 <= additional_requests <= 50_000
                or type(additional_bytes) is not int or not 1 <= additional_bytes <= 4_294_967_296
                or not set(replacement.endpoints) <= allowed
                or replacement.maximum_response_bytes > min(
                    self.policy.maximum_response_bytes, 4_194_304,
                )
                or replacement.timeout_seconds > self.policy.timeout_seconds
                or replacement.cadence_seconds < max(60, self.policy.cadence_seconds)
                or replacement.window_seconds != 3600
                or replacement.window_maximum_requests > 1000
                or replacement.window_maximum_bytes > 134_217_728
                or replacement.cohort_limit > min(5, self.policy.cohort_limit)
                or replacement.memory_max_bytes > min(536_870_912, self.policy.memory_max_bytes)
                or replacement.cpu_quota_percent > min(50, self.policy.cpu_quota_percent)
                or replacement.minimum_free_disk_bytes < max(
                    9_663_676_416, self.policy.minimum_free_disk_bytes,
                )
                or replacement.closure_request_reserve < self.policy.closure_request_reserve
                or replacement.closure_byte_reserve < self.policy.closure_byte_reserve
                or replacement.retention_days != self.policy.retention_days
                or replacement.backup_generations != self.policy.backup_generations):
            raise AcquisitionBlockedError("finite_campaign_outside_explicit_envelope")
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT policy_digest,stopped FROM authority").fetchone() != (
                self.policy.digest, 1,
            ):
                raise AcquisitionBlockedError("finite_campaign_requires_matching_STOP")
            count, charged = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0) "
                "FROM reservations"
            ).fetchone()
            if (replacement.maximum_requests != count + additional_requests
                    or replacement.maximum_bytes != charged + additional_bytes):
                raise AcquisitionBlockedError("finite_campaign_cumulative_limits_mismatch")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS finite_campaign_grants ("
                "authorization_reference TEXT PRIMARY KEY,old_digest TEXT,new_digest TEXT UNIQUE,"
                "granted_at TEXT,prior_requests INTEGER,prior_bytes INTEGER,"
                "additional_requests INTEGER,additional_bytes INTEGER,"
                "old_policy TEXT,new_policy TEXT,baseline_rowid INTEGER NOT NULL)"
            )
            if connection.execute("SELECT COUNT(*) FROM finite_campaign_grants").fetchone()[0]:
                raise AcquisitionBlockedError(
                    "finite_campaign_already_granted_no_automatic_renewal",
                )
            baseline = connection.execute(
                "SELECT COALESCE(MAX(rowid),0) FROM reservations",
            ).fetchone()[0]
            connection.execute("INSERT INTO finite_campaign_grants VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                authorization_reference, self.policy.digest, replacement.digest, now.isoformat(),
                count, charged, additional_requests, additional_bytes,
                json.dumps(self.policy.to_dict(), sort_keys=True),
                json.dumps(replacement.to_dict(), sort_keys=True),
                baseline,
            ))
            connection.execute("UPDATE authority SET policy_digest=? WHERE singleton=1", (
                replacement.digest,
            ))
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
            campaign = None
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='finite_campaign_grants'"
            ).fetchone():
                grant = connection.execute(
                    "SELECT baseline_rowid,additional_requests,additional_bytes "
                    "FROM finite_campaign_grants"
                ).fetchone()
                if grant:
                    new_count, new_bytes, first_attempt = connection.execute(
                        "SELECT COUNT(*),COALESCE(SUM(COALESCE(actual_bytes,reserved_bytes)),0),"
                        "MIN(attempted_at) FROM reservations WHERE rowid>?", (grant[0],),
                    ).fetchone()
                    campaign = {"requests_charged": new_count, "bytes_charged": new_bytes,
                                "first_attempt_at": first_attempt,
                                "requests_remaining": grant[1] - new_count,
                                "bytes_remaining": grant[2] - new_bytes}
        return {
            "policy_digest": authority[0],
            "stopped": bool(authority[1]),
            "requests_charged": count,
            "bytes_charged": charged,
            "uncertain_requests": uncertain,
            "requests_remaining": max(0, self.policy.maximum_requests - count),
            "bytes_remaining": max(0, self.policy.maximum_bytes - charged),
            "campaign": campaign,
        }
