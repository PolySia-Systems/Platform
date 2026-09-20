"""Durable research-run command journal.

The worker owns Manifest mutation. Clients record commands only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from polysia.deployment.research_run_contract import canonical_dumps
from polysia.storage.research_evidence import ExclusiveWriterLock, ResearchWriterLockError

COMMAND_LOG_NAME = "command-log.json"
STOP_KIND = "stop"
DISPOSITION_ACCEPTED = "ACCEPTED"
DISPOSITION_APPLIED = "APPLIED"
DISPOSITION_REJECTED = "REJECTED"


class ResearchRunCommandError(RuntimeError):
    """Durable command conflict or validation failure."""


@dataclass(frozen=True, slots=True)
class ResearchRunCommand:
    command_id: str
    kind: str
    content_fingerprint: str
    expected_revision: int
    disposition: str
    payload: dict[str, object]
    observed_result: dict[str, object] | None = None
    requested_at: str | None = None
    applied_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "applied_at": self.applied_at,
            "command_id": self.command_id,
            "content_fingerprint": self.content_fingerprint,
            "disposition": self.disposition,
            "expected_revision": self.expected_revision,
            "kind": self.kind,
            "observed_result": self.observed_result,
            "payload": dict(self.payload),
            "requested_at": self.requested_at,
        }


class ResearchCommandJournal:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._path = root / COMMAND_LOG_NAME
        self._lock = ExclusiveWriterLock(
            root / "commands",
            rejected_message="second command writer rejected for research run workspace",
        )

    def record(
        self,
        *,
        command_id: str,
        kind: str,
        payload: Mapping[str, object],
        expected_revision: int,
        current_revision: int,
        clock: datetime,
    ) -> ResearchRunCommand:
        fingerprint = content_fingerprint(kind, payload)
        identifier = _require_command_id(command_id)
        try:
            self._lock.acquire()
        except ResearchWriterLockError as error:
            raise ResearchRunCommandError(str(error)) from error
        try:
            log = self._load()
            existing = log.get(identifier)
            if existing is not None:
                command = _command_from_dict(existing)
                if command.content_fingerprint != fingerprint:
                    raise ResearchRunCommandError(
                        "command_id was already used with different research-run content"
                    )
                return command
            if expected_revision != current_revision:
                raise ResearchRunCommandError("research-run command expected_revision is stale")
            command = ResearchRunCommand(
                command_id=identifier,
                kind=kind,
                content_fingerprint=fingerprint,
                expected_revision=expected_revision,
                disposition=DISPOSITION_ACCEPTED,
                payload=dict(payload),
                requested_at=_utc_text(clock),
            )
            log[identifier] = command.to_dict()
            self._store(log)
            return command
        finally:
            self._lock.release()

    def mark_applied(
        self,
        command_id: str,
        *,
        observed_result: Mapping[str, object],
        clock: datetime,
    ) -> ResearchRunCommand | None:
        identifier = _require_command_id(command_id)
        try:
            self._lock.acquire()
        except ResearchWriterLockError as error:
            raise ResearchRunCommandError(str(error)) from error
        try:
            log = self._load()
            existing = log.get(identifier)
            if existing is None:
                return None
            command = _command_from_dict(existing)
            if command.disposition == DISPOSITION_APPLIED:
                return command
            applied = ResearchRunCommand(
                command_id=command.command_id,
                kind=command.kind,
                content_fingerprint=command.content_fingerprint,
                expected_revision=command.expected_revision,
                disposition=DISPOSITION_APPLIED,
                payload=dict(command.payload),
                observed_result=dict(observed_result),
                requested_at=command.requested_at,
                applied_at=_utc_text(clock),
            )
            log[identifier] = applied.to_dict()
            self._store(log)
            return applied
        finally:
            self._lock.release()

    def get(self, command_id: str) -> ResearchRunCommand | None:
        log = self._load()
        payload = log.get(_require_command_id(command_id))
        if payload is None:
            return None
        return _command_from_dict(payload)

    def latest_stop(self) -> ResearchRunCommand | None:
        chosen: ResearchRunCommand | None = None
        for payload in self._load().values():
            command = _command_from_dict(payload)
            if command.kind != STOP_KIND:
                continue
            if chosen is None or str(command.requested_at or "") > str(chosen.requested_at or ""):
                chosen = command
        return chosen

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ResearchRunCommandError("research-run command log is not valid JSON") from error
        commands = payload.get("commands") if isinstance(payload, dict) else None
        if not isinstance(commands, dict):
            raise ResearchRunCommandError("research-run command log is invalid")
        return {
            str(key): dict(value)
            for key, value in commands.items()
            if isinstance(value, dict)
        }

    def _store(self, commands: Mapping[str, Mapping[str, object]]) -> None:
        text = json.dumps({"commands": dict(commands)}, sort_keys=True, indent=2) + "\n"
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self._path)


def content_fingerprint(kind: str, payload: Mapping[str, object]) -> str:
    encoded = canonical_dumps({"kind": kind, "payload": dict(payload)})
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _command_from_dict(payload: Mapping[str, object]) -> ResearchRunCommand:
    observed = payload.get("observed_result")
    raw_payload = payload.get("payload")
    command_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    return ResearchRunCommand(
        command_id=str(payload.get("command_id") or ""),
        kind=str(payload.get("kind") or ""),
        content_fingerprint=str(payload.get("content_fingerprint") or ""),
        expected_revision=_as_int(payload.get("expected_revision")),
        disposition=str(payload.get("disposition") or DISPOSITION_ACCEPTED),
        payload=command_payload,
        observed_result=dict(observed) if isinstance(observed, dict) else None,
        requested_at=None
        if payload.get("requested_at") is None
        else str(payload.get("requested_at")),
        applied_at=None if payload.get("applied_at") is None else str(payload.get("applied_at")),
    )


def _require_command_id(command_id: str) -> str:
    text = command_id.strip()
    if not text or len(text) > 128:
        raise ResearchRunCommandError("research-run command_id is invalid")
    return text


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
