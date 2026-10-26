"""H1 transport helpers over the existing redacted publication and command owner."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs

from polysia.control.scoped_operations import Operation
from polysia.control.service import ControlService
from polysia.monitoring.console_contract import (
    API_VERSION,
    RELEASE,
    Action,
    ActionCatalog,
    ApplyRequest,
    Context,
    OperationName,
    Preview,
    PreviewRequest,
    Receipt,
    Receipts,
    Session,
    Snapshot,
)
from polysia.monitoring.console_projection import (
    UNKNOWN_SCOPE,
    ConsoleReadModel,
    component,
    fingerprint,
    project_supervision,
)

if TYPE_CHECKING:
    from polysia.monitoring.console import ConsoleApplication

PREFIX = "/api/console/v1"
CATALOG = {
    "session.stop": (
        "STOP financial session",
        "Independent STOP; exposure may remain and automatic exits may stop.",
    ),
    "session.drain": (
        "Drain financial entries",
        "Block new entries; permitted protective work remains with the financial owner.",
    ),
    "shadow.drain": (
        "Drain Shadow experiment",
        "Stop new simulated entries for this registered experiment.",
    ),
    "shadow.finalize": (
        "Finalize Shadow experiment",
        "Request owner finalization; existing owner admission checks still apply.",
    ),
}


def parameters(query: str, allowed: set[str]) -> dict[str, str]:
    if len(query) > 2048:
        raise ValueError("query_size_limit")
    parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    if set(parsed) - allowed or any(len(values) != 1 for values in parsed.values()):
        raise ValueError("invalid_query_fields")
    return {key: values[0] for key, values in parsed.items()}


class ConsoleGateway:
    def __init__(self, app: ConsoleApplication) -> None:
        self.app = app
        self._model: ConsoleReadModel | None = None

    def session(self, subject: str, role: str, now: datetime) -> Session:
        csrf = self.app._csrf(subject)
        return Session(
            api=API_VERSION,
            release=RELEASE,
            bundle=self.bundle_identity(),
            actor=subject,
            role=cast(Any, role),
            csrf=csrf,
            identity=fingerprint((subject, role, csrf)),
            server_time=now.isoformat(),
            valid_until=(now + timedelta(minutes=10)).isoformat(),
        )

    @staticmethod
    def bundle_identity() -> str | None:
        try:
            path = Path(__file__).with_name("human_console_assets") / "manifest.json"
            if path.stat().st_size > 32_768:
                return None
            value = json.loads(path.read_bytes())["source"]
            return (
                value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) else None
            )
        except OSError, ValueError, KeyError, TypeError:
            return None

    def model(self) -> ConsoleReadModel:
        raw = self.app._read_publication()
        generation = self.app._publication_generation
        if self._model is None or self._model.generation != generation:
            self._model = ConsoleReadModel(raw, generation)
        return self._model

    def action(self, subject: str, role: str, operation: str, target: str) -> Action | None:
        if role != "operator" or target not in self.app._scoped_targets:
            return None
        permitted = (
            ("session.stop",)
            if target.endswith(":stop")
            else ("session.drain",)
            if target.endswith(":drain")
            else ("shadow.drain", "shadow.finalize")
        )
        if operation not in permitted:
            return None
        identity = self.session(subject, role, datetime.now(UTC)).identity
        protective = operation in {"session.stop", "session.drain"}
        generation = None
        if not protective:
            try:
                generation = self.model().generation
            except OSError, ValueError, TypeError, KeyError:
                return None
        label, impact = CATALOG[operation]
        return Action(
            operation=cast(OperationName, operation),
            target=target,
            label=label,
            impact=impact,
            context=fingerprint((identity, target, operation, generation, self.bundle_identity())),
            protective=protective,
        )

    def actions(self, subject: str, role: str, *, protective_only: bool = False) -> list[Action]:
        if role != "operator":
            return []
        result = []
        for target in sorted(self.app._scoped_targets):
            operations = (
                ("session.stop",)
                if target.endswith(":stop")
                else (
                    ("session.drain",)
                    if target.endswith(":drain")
                    else ("shadow.drain", "shadow.finalize")
                )
            )
            for operation in operations:
                if protective_only and not operation.startswith("session."):
                    continue
                action = self.action(subject, role, operation, target)
                if action is not None:
                    result.append(action)
        return result

    def snapshot(self, subject: str, role: str, now: datetime) -> Snapshot:
        try:
            model = self.model()
            context = model.context()
            financial, meta = model.financial(now)
            components = [
                component(
                    "publication",
                    model.publication,
                    now=now,
                    generation=model.generation,
                    scope=model.scope,
                ),
                meta,
            ]
        except OSError, ValueError, TypeError, KeyError:
            context = Context(
                dataset="UNKNOWN",
                environment="UNKNOWN",
                configured_mode="UNKNOWN",
                observed_mode="UNKNOWN",
                scope=UNKNOWN_SCOPE,
                generation=None,
                provenance="publication_unavailable_or_incompatible",
            )
            financial = None
            components = [
                component(name, None, now=now, generation=None, scope=UNKNOWN_SCOPE)
                for name in ("publication", "financial")
            ]
        raw = None
        try:
            path = self.app._publication.parent / "supervisor-status.json"
            with path.open("rb") as stream:
                data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError("supervision_size_limit")
            raw = json.loads(data)
            if not isinstance(raw, dict):
                raw = None
        except OSError, ValueError:
            pass
        supervision, meta = project_supervision(raw, now=now, scope=context.scope)
        components.append(meta)
        blocker = (
            "Financial authority is not granted by this Console. "
            "Review the protected operating contract."
        )
        if financial is not None and financial.reconciliation == "BLOCKED":
            blocker = (
                "Reconciliation is blocked. Preserve evidence and reconcile through "
                "the protected operator route before any financial continuation."
            )
        elif financial is not None and financial.unknown_orders:
            blocker = (
                "Order outcomes remain UNKNOWN. Preserve reservations; "
                "inspect exact order evidence through the protected owner."
            )
        if any(
            item.state in {"STALE", "INCOMPATIBLE", "UNAVAILABLE", "PARTIAL"} for item in components
        ):
            blocker = (
                "Evidence needs attention. Inspect component validity; "
                "use the protected supervisor / CLI for independent STOP."
            )
        if supervision.status == "STOPPED":
            blocker = (
                "Independent STOP is observed. Preserve STOP and reconcile "
                "remaining exposure through the protected operator route."
            )
        return Snapshot(
            api=API_VERSION,
            release=RELEASE,
            atomic=False,
            server_time=now.isoformat(),
            context=context,
            components=components,
            financial=financial,
            supervision=supervision,
            blocker=blocker,
            actions=self.actions(subject, role),
        )

    @staticmethod
    def receipt(row: dict[str, Any]) -> Receipt:
        preview = json.loads(row["preview"])
        result = json.loads(row["result"]) if row["result"] else {}
        effect = result.get("effect", "NOT_OBSERVED")
        # FAILED/UNKNOWN_OR_FAILED is never proof that the owner did not execute.
        if row["status"] in {"FAILED", "CLAIMED"} or effect not in {"OBSERVED", "NOT_OBSERVED"}:
            effect = "UNKNOWN"
        return Receipt(
            idempotency_key=row["idempotency"],
            operation=preview["operation"],
            target=row["target"],
            revision=row["revision"],
            phase=row["status"],
            effect=effect,
            reason=result.get("reason"),
        )

    def get(self, path: str, query: str, subject: str, role: str) -> object:
        now = datetime.now(UTC)
        if path == PREFIX + "/session":
            parameters(query, set())
            return self.session(subject, role, now).model_dump()
        if path == PREFIX + "/snapshot":
            parameters(query, set())
            return self.snapshot(subject, role, now).model_dump()
        if path == PREFIX + "/protective-actions":
            parameters(query, set())
            return ActionCatalog(
                actions=self.actions(subject, role, protective_only=True)
            ).model_dump()
        if path == PREFIX + "/records":
            args = parameters(query, {"kind", "q", "state", "sort", "limit", "cursor"})
            return (
                self.model()
                .page(
                    kind=args.get("kind", "order"),
                    query=args.get("q", ""),
                    state=args.get("state", ""),
                    sort=args.get("sort", "identity"),
                    limit=int(args.get("limit", "50")),
                    cursor=args.get("cursor", ""),
                )
                .model_dump()
            )
        if path == PREFIX + "/detail":
            args = parameters(query, {"kind", "identity", "generation"})
            return (
                self.model().detail(args["kind"], args["identity"], args["generation"]).model_dump()
            )
        if path == PREFIX + "/receipts":
            args = parameters(query, {"key", "cursor", "limit"})
            limit = int(args.get("limit", "50"))
            before = None
            if args.get("cursor"):
                token, offset = args["cursor"].split(":")
                # Current authorization scope is part of the history cursor.
                if token != fingerprint((subject, role, sorted(self.app._scoped_targets))):
                    raise ValueError("receipt_scope_differs")
                before = int(offset)
            rows = self.app._commands.console_receipts(
                subject=subject,
                targets=self.app._scoped_targets,
                key=args.get("key"),
                before=before,
                limit=limit,
            )
            cursor = (
                None
                if len(rows) < limit
                else (
                    fingerprint((subject, role, sorted(self.app._scoped_targets)))
                    + ":"
                    + str(rows[-1]["rowid"])
                )
            )
            return Receipts(
                items=[self.receipt(row) for row in rows], next_cursor=cursor
            ).model_dump()
        raise KeyError("unknown_route")

    def mutate(self, path: str, payload: dict[str, Any], subject: str, role: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        session = self.session(subject, role, now)
        if role != "operator" or payload.get("identity") != session.identity:
            raise ValueError("authentication_changed")
        if path == PREFIX + "/preview":
            request = PreviewRequest.model_validate(payload)
            action = self.action(subject, role, request.operation, request.target)
            if action is None or action.context != request.context:
                raise ValueError("context_or_target_changed")
            preview = ControlService.preview_scoped(
                self.app._commands,
                operation=cast(Operation, request.operation),
                target=request.target,
                actor=subject,
                role=role,
                allowed_targets=self.app._scoped_targets,
                now=now,
            )
            self.app._commands.bind_console_preview(
                preview.fingerprint, context=request.context, identity=session.identity
            )
            return Preview(
                preview_id=preview.fingerprint,
                actor=subject,
                operation=preview.operation,
                target=preview.target,
                context=request.context,
                identity=session.identity,
                expected_revision=preview.expected_revision,
                expires_at=preview.expires_at.isoformat(),
                impact=action.impact,
            ).model_dump()
        request_apply = ApplyRequest.model_validate(payload)
        stored = self.app._commands.console_preview(
            request_apply.preview_id, context=request_apply.context, identity=session.identity
        )
        action = self.action(subject, role, stored["operation"], stored["target"])
        if action is None or action.context != request_apply.context:
            raise ValueError("context_changed")
        self.app._commands.submit_scoped(
            subject=subject,
            role=role,
            preview_id=request_apply.preview_id,
            expected_revision=request_apply.expected_revision,
            idempotency_key=request_apply.idempotency_key,
            now=now,
            allowed_targets=self.app._scoped_targets,
        )
        rows = self.app._commands.console_receipts(
            subject=subject, targets=self.app._scoped_targets, key=request_apply.idempotency_key
        )
        return self.receipt(rows[0]).model_dump()
