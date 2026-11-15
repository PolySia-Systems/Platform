"""Finite independent supervision and verified backup publication; no venue I/O."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from polysia.deployment.session_supervision import SessionSupervisor, committed_checkpoint
from polysia.domain.financial_session import (
    SessionAuthorization,
    SessionBlocked,
    canonical_json,
    utc,
)
from polysia.security.session_authority import SessionCustody
from polysia.storage.atomic_files import read_publication_bytes


def publish_control_file(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise SessionBlocked("control_publication_symlink_denied")
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != "nt":
        temporary.chmod(0o640)
    temporary.replace(path)


def require_offsite_proof(record: dict[str, Any], *, now: datetime, maximum_age: int) -> None:
    proof = record.get("offsite")
    if not isinstance(proof, dict) or (
        proof.get("version") != "session-offsite-backup/v1"
        or proof.get("restore_verified") is not True
        or proof.get("authority_reissued") is not False
        or proof.get("custody_included") is not False
        or proof.get("financial_writer") != "FORBIDDEN"
        or proof.get("checkpoint") != record.get("checkpoint")
        or proof.get("artifact_sha256") != record.get("artifact_sha256")
        or proof.get("authority_fingerprint") != record.get("authority_fingerprint")
    ):
        raise SessionBlocked("matching_offsite_restore_required")
    fingerprint = proof.get("authority_fingerprint")
    checkpoint = proof.get("checkpoint")
    if (
        not isinstance(fingerprint, str)
        or not re.fullmatch("[a-f0-9]{64}", fingerprint)
        or not isinstance(checkpoint, dict)
        or checkpoint.get("authority_fingerprint") != fingerprint
        or type(checkpoint.get("sequence")) is not int
        or checkpoint["sequence"] < 0
        or not isinstance(checkpoint.get("state_digest"), str)
        or not re.fullmatch("[a-f0-9]{64}", checkpoint["state_digest"])
        or not isinstance(proof.get("artifact_sha256"), str)
        or not re.fullmatch("[a-f0-9]{64}", proof["artifact_sha256"])
    ):
        raise SessionBlocked("bound_offsite_checkpoint_required")
    try:
        at = utc(datetime.fromisoformat(proof["observed_at"]))
        age = (utc(now) - at).total_seconds()
    except (KeyError, TypeError, ValueError) as error:
        raise SessionBlocked("offsite_observation_time_required") from error
    if not 0 <= age <= maximum_age:
        raise SessionBlocked("offsite_restore_stale_or_future")


class ContinuousSessionSupervisor:
    """ARMED means STOP retained; only the real worker can establish liveness.

    This process never manufactures worker heartbeats and never creates or renews
    financial authority. release_stop is an explicit privileged owner action.
    """

    def __init__(
        self,
        authority: SessionAuthorization,
        custody: SessionCustody,
        supervisor: SessionSupervisor,
        *,
        clock: Callable[[], datetime],
        wait: Callable[[float], None],
        release_stop: bool = False,
        startup_timeout_seconds: int = 30,
        status_path: Path | None = None,
    ) -> None:
        if not 0 < startup_timeout_seconds <= 60:
            raise SessionBlocked("bounded_control_startup_required")
        self.authority, self.custody, self.supervisor = authority, custody, supervisor
        self.clock, self.wait, self.release_stop = clock, wait, release_stop
        self.startup_timeout_seconds = startup_timeout_seconds
        self.status_path = status_path

    def run(self, *, maximum_ticks: int) -> dict[str, Any]:
        if not 1 <= maximum_ticks <= 200000:
            raise SessionBlocked("finite_control_tick_count_required")
        started = utc(self.clock())
        active = False
        checks = 0
        previous = started
        published_at: datetime | None = None
        try:
            for _ in range(maximum_ticks):
                now = utc(self.clock())
                if now < previous:
                    raise SessionBlocked("continuous_control_clock_regressed")
                previous = now
                if now >= self.authority.protective_until:
                    return {"status": "DEADLINE_STOP", "checks": checks}
                state = self.custody.snapshot(self.authority.fingerprint)
                if self.status_path is not None and (
                    published_at is None or (now - published_at).total_seconds() >= 1
                ):
                    publish_control_file(
                        self.status_path,
                        {
                            "status": "RUNNING_CONTROL" if active else "ARMED_STOP",
                            "observed_at": now,
                            "authority": self.authority.fingerprint,
                            "checks": checks,
                            "worker_heartbeat_generated": False,
                        },
                    )
                    published_at = now
                if state["revoked"] or (
                    state["stopped"] and state["stop_reason"] != "commissioning_stop"
                ):
                    return {"status": "LATCHED_STOP", "checks": checks}
                if state["stopped"] and not self.release_stop:
                    # Backup publication can continue under STOP. Do not refresh
                    # custody health while there is no financial worker.
                    self.wait(0.05)
                    continue
                raw = read_publication_bytes(self.supervisor.backup_receipt, maximum_bytes=8192)
                record = json.loads(raw)
                require_offsite_proof(
                    record, now=now, maximum_age=self.supervisor.policy.backup_maximum_age_seconds
                )
                if not active and self.release_stop:
                    self.authority.assert_action(self.authority.binding, now, "ENTRY")
                    heartbeat = json.loads(
                        read_publication_bytes(self.supervisor.outbox, maximum_bytes=8192)
                    )
                    worker_at = utc(datetime.fromisoformat(heartbeat["worker_at"]))
                    if worker_at < started:
                        if (now - started).total_seconds() >= self.startup_timeout_seconds:
                            raise SessionBlocked("real_worker_startup_not_observed")
                        self.wait(0.05)
                        continue
                checkpoint = self.supervisor.inspect()
                checks += 1
                if not active and self.release_stop:
                    ack = self.custody.snapshot(self.authority.fingerprint)
                    supervised = ack.get("supervised_at")
                    if (
                        not isinstance(supervised, str)
                        or datetime.fromisoformat(supervised) < started
                        or ack.get("checkpoint") != canonical_json(asdict(checkpoint))
                        or checkpoint
                        != committed_checkpoint(self.supervisor.journal, self.supervisor.witness)
                    ):
                        if (now - started).total_seconds() >= self.startup_timeout_seconds:
                            raise SessionBlocked("exact_fresh_startup_ACK_required")
                        self.wait(0.05)
                        continue
                    self.custody.release_stop(self.authority.fingerprint, expected=checkpoint)
                active = True
                self.wait(0.05)
            return {"status": "FINITE_CONTROL_STOP", "checks": checks}
        except OSError, ValueError, KeyError, TypeError, SessionBlocked:
            if self.supervisor.incidents is not None:
                self.supervisor.incidents.record(
                    "backup_unprotected",
                    scope=self.authority.run_id,
                    reason_code="continuous_control_failure",
                    next_action="Retain STOP; inspect backup and independent worker health",
                )
            raise
        finally:
            state = self.custody.snapshot(self.authority.fingerprint)
            if not state["stopped"] or state["stop_reason"] == "commissioning_stop":
                self.custody.stop(self.authority.fingerprint, reason="continuous_control_ended")
            if self.status_path is not None:
                publish_control_file(
                    self.status_path,
                    {
                        "status": "STOP",
                        "observed_at": self.clock(),
                        "authority": self.authority.fingerprint,
                        "checks": checks,
                        "worker_heartbeat_generated": False,
                    },
                )
