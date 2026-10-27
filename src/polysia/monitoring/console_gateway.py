"""H1 transport helpers over the existing redacted publication and command owner."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlencode

from polysia.control.scoped_operations import OPERATIONS, Operation
from polysia.control.service import ControlService
from polysia.monitoring.console_bundle import verify_bundle
from polysia.monitoring.console_contract import (
    API_VERSION,
    RELEASE,
    Action,
    ActionCatalog,
    ApplyRequest,
    Argument,
    Choice,
    Context,
    Fact,
    OperationName,
    Preview,
    PreviewRequest,
    Receipt,
    Receipts,
    Scope,
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
    "shadow.create": (
        "Create Shadow experiment",
        "Create one unused registered slot with independent virtual capital "
        "and a registered frozen policy. No real account execution.",
    ),
    "shadow.clone": (
        "Clone Shadow experiment",
        "Create an unused slot from another existing slot; independent virtual "
        "capital and frozen cohort are retained.",
    ),
    "shadow.start": (
        "Start Shadow experiment",
        "Start a CREATED slot; acquisition and owner admission remain within "
        "existing authority and hard caps.",
    ),
    "shadow.resume": (
        "Resume Shadow experiment",
        "Resume an unarchived DRAINING Shadow slot only. Financial resume is unavailable.",
    ),
    "shadow.archive": (
        "Archive Shadow experiment",
        "Archive a DRAINING or FINALIZED slot; retain censored inventory and "
        "immutable history. No closure is implied.",
    ),
    "shadow.compare": (
        "Compare Shadow experiments",
        "Compare two started slots from one frozen cohort. Same-tape identity "
        "needs matching retained digests; independent returns are not summed.",
    ),
    "policy.stage": (
        "Stage registered Shadow policy",
        "Stage a registered template on a CREATED slot only. Existing "
        "positions retain their frozen policy; financial policy editing is "
        "deferred.",
    ),
    "acquisition.stop": (
        "STOP acquisition",
        "Halt source acquisition; financial workers and retained exposure are separate.",
    ),
    "acquisition.drain": (
        "Drain acquisition entries",
        "Request exit-only Shadow acquisition; this does not drain a financial session.",
    ),
    "acquisition.resume": (
        "Resume authorized acquisition",
        "Resume only within the existing acquisition owner's current authority and hard caps.",
    ),
    "acquisition.export": (
        "Retain protected report",
        "Request an immutable redacted report; optional paired UTC bounds select "
        "retained evidence.",
    ),
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
    parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=16)
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
            return cast(str, verify_bundle()["source"])
        except OSError, ValueError, KeyError, TypeError:
            return None

    def model(self) -> ConsoleReadModel:
        raw = self.app._read_publication()
        generation = self.app._publication_generation
        if self._model is None or self._model.generation != generation:
            self._model = ConsoleReadModel(raw, generation)
        return self._model

    def action(
        self, subject: str, role: str, operation: str, target: str, *, bundle: str | None = None
    ) -> Action | None:
        if role != "operator" or (
            target != "acquisition" and target not in self.app._scoped_targets
        ):
            return None
        permitted = (
            tuple(name for name in CATALOG if name.startswith("acquisition."))
            if target == "acquisition"
            else ("session.stop",)
            if target.endswith(":stop")
            else ("session.drain",)
            if target.endswith(":drain")
            else tuple(name for name in OPERATIONS if not name.startswith("session."))
        )
        if operation not in permitted:
            return None
        identity = fingerprint((subject, role, self.app._csrf(subject)))
        bundle = bundle or self.bundle_identity()
        if bundle is None:
            return None
        protective = operation in {
            "session.stop",
            "session.drain",
            "acquisition.stop",
            "acquisition.drain",
        }
        generation = None
        arguments: list[Argument] = []
        if not protective:
            try:
                generation = self.model().generation
            except OSError, ValueError, TypeError, KeyError:
                return None
        argument = {
            "shadow.clone": "source",
            "shadow.compare": "other",
            "shadow.create": "policy_digest",
            "policy.stage": "policy_digest",
        }.get(operation)
        if argument:
            from polysia.monitoring.console_workspaces import obj, rows

            choices = []
            if argument == "policy_digest":
                for row in rows(obj(self.model().publication.get("shadow_lab")).get("policies"))[
                    :64
                ]:
                    value = row.get("digest")
                    if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
                        choices.append(
                            Choice(value=value, label=str(row.get("version") or value)[:256])
                        )
            else:
                choices = [
                    Choice(
                        value=row["target"],
                        label=row["target"] + " · " + str(row.get("phase", "UNKNOWN")),
                    )
                    for row in rows(
                        obj(self.model().publication.get("shadow_lab")).get("experiments")
                    )
                    if isinstance(row.get("target"), str)
                    and row["target"] in self.app._scoped_targets
                    and not row["target"].endswith((":stop", ":drain"))
                    and row["target"] != target
                    and (argument != "other" or row.get("experiment_id"))
                ][:64]
            if not choices:
                return None
            arguments = [
                Argument(
                    name=cast(Any, argument),
                    label="Registered " + argument.replace("_", " "),
                    kind="choice",
                    choices=choices,
                )
            ]
        elif operation == "acquisition.export":
            arguments = [
                Argument(
                    name=cast(Any, name),
                    label="Optional " + name + " (UTC)",
                    kind="utc",
                    choices=[],
                )
                for name in ("start", "end")
            ]
        label, impact = CATALOG[operation]
        return Action(
            operation=cast(OperationName, operation),
            target=target,
            label=label,
            impact=impact,
            context=fingerprint((identity, target, operation, generation, bundle)),
            protective=protective,
            arguments=arguments,
        )

    def actions(self, subject: str, role: str, *, protective_only: bool = False) -> list[Action]:
        if role != "operator":
            return []
        bundle = self.bundle_identity()
        if bundle is None:
            return []
        result = []
        for target in ["acquisition", *sorted(self.app._scoped_targets)]:
            operations = (
                tuple(name for name in CATALOG if name.startswith("acquisition."))
                if target == "acquisition"
                else ("session.stop",)
                if target.endswith(":stop")
                else (
                    ("session.drain",)
                    if target.endswith(":drain")
                    else tuple(sorted(OPERATIONS - {"session.stop", "session.drain"}))
                )
            )
            for operation in operations:
                if protective_only and operation not in {
                    "session.stop",
                    "session.drain",
                    "acquisition.stop",
                    "acquisition.drain",
                }:
                    continue
                action = self.action(subject, role, operation, target, bundle=bundle)
                if action is not None:
                    result.append(action)
        return result

    def snapshot(
        self, subject: str, role: str, now: datetime, override: ConsoleReadModel | None = None
    ) -> Snapshot:
        try:
            model = override or self.model()
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
                component(
                    "worker",
                    {"observed_at": model.publication.get("last_attempt")},
                    now=now,
                    generation=model.generation,
                    scope=UNKNOWN_SCOPE,
                ),
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
            if override is not None:
                raise ValueError("example_has_no_runtime_supervision")
            path = self.app._publication.parent / "supervisor-status.json"
            if path.is_symlink():
                raise ValueError("supervision_status_symlink")
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
        publisher = None
        try:
            if override is not None:
                raise ValueError("example_has_no_runtime_publisher")
            path = self.app._publication.parent / "publisher-status.json"
            if path.is_symlink():
                raise ValueError("publisher_status_symlink")
            with path.open("rb") as stream:
                encoded = stream.read(4097)
            if len(encoded) > 4096:
                raise ValueError("publisher_status_size_limit")
            candidate = json.loads(encoded)
            if isinstance(candidate, dict):
                publisher = candidate
        except OSError, ValueError:
            pass
        publisher_scope = UNKNOWN_SCOPE
        if (
            publisher
            and isinstance(publisher.get("scope"), str)
            and 0 < len(publisher["scope"]) <= 256
        ):
            publisher_scope = Scope(run=publisher["scope"], account=None, venue=None)
        meta = component("publisher", publisher, now=now, generation=None, scope=publisher_scope)
        if publisher and publisher.get("status") not in ("PUBLISHED", "OK"):
            meta = meta.model_copy(
                update={"state": "UNAVAILABLE", "reason": "publisher_failed_or_unknown"}
            )
        elif (
            publisher
            and publisher.get("scope") is not None
            and publisher.get("scope") != context.scope.run
        ):
            meta = meta.model_copy(
                update={"state": "INCOMPATIBLE", "reason": "publisher_scope_mismatch"}
            )
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
        ) and not (
            financial and (financial.reconciliation == "BLOCKED" or financial.unknown_orders)
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
        from polysia.monitoring.console_workspaces import facts, obj, rows, table

        preview = json.loads(row["preview"])
        result = obj(json.loads(row["result"])) if row["result"] else {}
        effect = result.get("effect", "NOT_OBSERVED")
        if preview["operation"].startswith("acquisition.") and row["status"] == "APPLIED":
            effect = "OBSERVED"
        # FAILED/UNKNOWN_OR_FAILED is never proof that the owner did not execute.
        if row["status"] in {"FAILED", "CLAIMED"} or effect not in {"OBSERVED", "NOT_OBSERVED"}:
            effect = "UNKNOWN"
        if (
            row["status"] == "APPLIED"
            and not preview["operation"].startswith("acquisition.")
            and result.get("effect") != "OBSERVED"
        ):
            effect = "UNKNOWN"
        comparison = obj(result.get("comparison"))
        summary = []
        for item in rows(comparison.get("results"))[:2]:
            report = obj(item.get("operator_summary"))
            summary.append(
                {
                    "experiment": obj(item.get("evidence_reference")).get("experiment_id"),
                    "virtual_pnl": report.get("follower_total_pnl"),
                    "valuation": report.get("follower_valuation"),
                    "confidence": obj(item.get("confidence")).get("level"),
                    "open_positions": report.get("open_position_count"),
                    "accounting": obj(item.get("accounting")).get("identity_status"),
                }
            )
        return Receipt(
            idempotency_key=row["idempotency"],
            operation=preview["operation"],
            target=row["target"],
            revision=row["revision"],
            phase=row["status"],
            effect=effect,
            reason=result.get("reason"),
            download=result.get("download")
            if isinstance(result.get("download"), str)
            and re.fullmatch(r"/reports/[a-f0-9]{64}\.json", result["download"])
            else None,
            facts=facts(
                comparison,
                "common_assumptions same_frozen_input_stream sum_of_returns accuracy_percent",
            )
            if comparison
            else [],
            tables=[
                table(
                    "Independent virtual comparison",
                    summary,
                    "experiment virtual_pnl valuation confidence open_positions accounting",
                )
            ]
            if comparison
            else [],
        )

    def get(self, path: str, query: str, subject: str, role: str) -> object:
        now = datetime.now(UTC)
        if len(query) > 2048:
            raise ValueError("query_size_limit")
        example = False
        parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=16)
        if "example" in parsed:
            if parsed.pop("example") != ["1"]:
                raise ValueError("unknown_dataset")
            example, role = True, "reader"
            query = urlencode(parsed, doseq=True)
        model = None
        if example:
            from polysia.monitoring.console_example import publication

            raw = publication()
            model = ConsoleReadModel(raw, fingerprint(raw))
        if path == PREFIX + "/session":
            parameters(query, set())
            return self.session(subject, role, now).model_dump()
        if path == PREFIX + "/snapshot":
            parameters(query, set())
            return self.snapshot(subject, role, now, model).model_dump()
        if path == PREFIX + "/workspace":
            from polysia.monitoring.console_workspaces import workspace

            args = parameters(query, {"panel"})
            return workspace(model or self.model(), args.get("panel", "system"), now).model_dump()
        if path == PREFIX + "/protective-actions":
            parameters(query, set())
            return ActionCatalog(
                actions=self.actions(subject, role, protective_only=True)
            ).model_dump()
        if path == PREFIX + "/records":
            args = parameters(query, {"kind", "q", "state", "source", "sort", "limit", "cursor"})
            return (
                (model or self.model())
                .page(
                    kind=args.get("kind", "order"),
                    query=args.get("q", ""),
                    state=args.get("state", ""),
                    sort=args.get("sort", "identity"),
                    limit=int(args.get("limit", "50")),
                    cursor=args.get("cursor", ""),
                    source=args.get("source", ""),
                )
                .model_dump()
            )
        if path == PREFIX + "/detail":
            args = parameters(query, {"kind", "identity", "generation"})
            return (
                (model or self.model())
                .detail(args["kind"], args["identity"], args["generation"])
                .model_dump()
            )
        if path == PREFIX + "/receipts":
            args = parameters(query, {"key", "cursor", "limit"})
            if example:
                return Receipts(items=[], next_cursor=None).model_dump()
            limit = int(args.get("limit", "50"))
            before = None
            if args.get("cursor"):
                token, encoded = args["cursor"].split(":")
                # Current authorization scope is part of the history cursor.
                if token != fingerprint((subject, role, sorted(self.app._scoped_targets))):
                    raise ValueError("receipt_scope_differs")
                decoded = json.loads(base64.urlsafe_b64decode(encoded))
                if (
                    not isinstance(decoded, list)
                    or len(decoded) != 2
                    or not all(isinstance(v, str) for v in decoded)
                ):
                    raise ValueError("invalid_history_cursor")
                before = (decoded[0], decoded[1])
            rows = self.app._commands.human_receipts(
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
                    + base64.urlsafe_b64encode(
                        json.dumps([rows[-1]["at"], rows[-1]["idempotency"]]).encode()
                    ).decode()
                )
            )
            return Receipts(
                items=[self.receipt(row) for row in rows], next_cursor=cursor
            ).model_dump()
        raise KeyError("unknown_route")

    def mutate(self, path: str, payload: dict[str, Any], subject: str, role: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        session = self.session(subject, role, now)
        if session.bundle is None:
            raise ValueError("console_bundle_unavailable")
        if role != "operator" or payload.get("identity") != session.identity:
            raise ValueError("authentication_changed")
        if path == PREFIX + "/preview":
            request = PreviewRequest.model_validate(payload)
            action = self.action(
                subject, role, request.operation, request.target, bundle=session.bundle
            )
            if action is None or action.context != request.context:
                raise ValueError("context_or_target_changed")
            self.check_arguments(action, request.arguments)
            scoped_arguments = dict(request.arguments)
            if request.operation == "shadow.clone":
                from polysia.monitoring.console_workspaces import obj
                from polysia.monitoring.console_workspaces import rows as workspace_rows

                source = next(
                    (
                        row
                        for row in workspace_rows(
                            obj(self.model().publication.get("shadow_lab")).get("experiments")
                        )
                        if row.get("target") == request.arguments["source"]
                    ),
                    None,
                )
                value = source.get("policy_digest") if source else None
                if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
                    raise ValueError("clone_source_policy_unknown")
                scoped_arguments["source_policy_digest"] = value
            if request.operation.startswith("acquisition."):
                record = dict(
                    actor=subject,
                    operation=request.operation,
                    target="acquisition",
                    arguments=request.arguments,
                    context=request.context,
                    identity=session.identity,
                    expected_revision=self.app._commands.acquisition_revision(),
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(minutes=2)).isoformat(),
                )
                identity = fingerprint(record)
                self.app._commands.save_acquisition_preview(identity, record)
                return Preview(
                    preview_id=identity,
                    actor=subject,
                    operation=request.operation,
                    target="acquisition",
                    context=request.context,
                    identity=session.identity,
                    expected_revision=cast(int, record["expected_revision"]),
                    expires_at=cast(str, record["expires_at"]),
                    impact=action.impact,
                    arguments=[Fact(label=k, value=v) for k, v in request.arguments.items()],
                ).model_dump()
            preview = ControlService.preview_scoped(
                self.app._commands,
                operation=cast(Operation, request.operation),
                target=request.target,
                actor=subject,
                role=role,
                allowed_targets=self.app._scoped_targets,
                now=now,
                arguments=tuple(sorted(scoped_arguments.items())),
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
                arguments=[Fact(label=k, value=v) for k, v in scoped_arguments.items()],
            ).model_dump()
        request_apply = ApplyRequest.model_validate(payload)
        acquisition = self.app._commands.acquisition_preview(request_apply.preview_id)
        if acquisition is not None:
            action = self.action(
                subject, role, acquisition["operation"], "acquisition", bundle=session.bundle
            )
            if (
                fingerprint(acquisition) != request_apply.preview_id
                or acquisition["actor"] != subject
                or acquisition["identity"] != session.identity
                or request_apply.context != acquisition["context"]
                or action is None
                or action.context != request_apply.context
                or request_apply.expected_revision != acquisition["expected_revision"]
                or not datetime.fromisoformat(acquisition["created_at"])
                <= now
                < datetime.fromisoformat(acquisition["expires_at"])
            ):
                raise ValueError("acquisition_preview_changed_or_expired")
            self.check_arguments(action, acquisition["arguments"])
            self.app._commands.submit(
                subject=subject,
                action=acquisition["operation"].split(".")[1],
                parameters=acquisition["arguments"],
                expected_revision=request_apply.expected_revision,
                idempotency_key=request_apply.idempotency_key,
            )
            rows = self.app._commands.human_receipts(
                subject=subject,
                targets=self.app._scoped_targets,
                key=request_apply.idempotency_key,
                before=None,
                limit=1,
            )
            return self.receipt(rows[0]).model_dump()
        stored = self.app._commands.console_preview(
            request_apply.preview_id, context=request_apply.context, identity=session.identity
        )
        action = self.action(
            subject, role, stored["operation"], stored["target"], bundle=session.bundle
        )
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

    @staticmethod
    def check_arguments(action: Action, arguments: dict[str, str]) -> None:
        if action.operation == "acquisition.export":
            if arguments and set(arguments) != {"start", "end"}:
                raise ValueError("paired_UTC_bounds_required")
            if arguments:
                start, end = (datetime.fromisoformat(arguments[key]) for key in ("start", "end"))
                if start >= end or any(value.utcoffset() != timedelta(0) for value in (start, end)):
                    raise ValueError("increasing_UTC_bounds_required")
        elif set(arguments) != {item.name for item in action.arguments}:
            raise ValueError("registered_arguments_required")
        for field in action.arguments:
            if field.kind == "choice" and arguments.get(field.name) not in {
                choice.value for choice in field.choices
            }:
                raise ValueError("argument_not_registered")
