"""Console v1 wire contract. Publications are evidence, never execution permission."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

API_VERSION: Literal["console/v1"] = "console/v1"
RELEASE: Literal["0.4.0"] = "0.4.0"
Identity = Annotated[str, Field(min_length=1, max_length=256)]
Fingerprint = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def valid_instant(value: str) -> str:
    datetime.fromisoformat(value)
    return value


Instant = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$",
        max_length=32,
    ),
    AfterValidator(valid_instant),
]
Exact = Annotated[str, Field(pattern=r"^-?(0|[1-9]\d*)(\.\d+)?([Ee][+-]?\d+)?$", max_length=128)]
Mode = Literal["DATA_ONLY", "PAPER", "LIVE", "UNKNOWN"]
Validity = Literal["AVAILABLE", "EMPTY", "STALE", "PARTIAL", "UNAVAILABLE", "INCOMPATIBLE"]
OperationName = Literal["shadow.drain", "shadow.finalize", "session.stop", "session.drain"]


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Scope(Wire):
    run: Identity | None
    account: Identity | None
    venue: Identity | None


class Context(Wire):
    dataset: Literal["RETAINED", "SYNTHETIC", "UNKNOWN"]
    environment: Literal["production", "development", "test", "UNKNOWN"]
    configured_mode: Mode
    observed_mode: Mode
    scope: Scope
    generation: Fingerprint | None
    provenance: Identity


class Component(Wire):
    name: Literal["publication", "financial", "supervision"]
    state: Validity
    observed_at: Instant | None
    valid_until: Instant | None
    generation: Identity | None
    scope: Scope
    reason: Identity


class Money(Wire):
    value: Exact | None
    unit: Identity | None
    meaning: Identity


class Financial(Wire):
    status: Literal["RUNNING", "DRAIN", "STOP", "UNKNOWN"]
    authority: Literal["DENIED", "EXPIRED", "NOT_STARTED", "WITHIN_WINDOW", "UNKNOWN"]
    authority_until: Instant | None
    reconciliation: Literal["MATCHED", "BLOCKED", "UNKNOWN"]
    economics: Identity
    cash: Money
    exposure: Money
    reserved: Money
    positions: Annotated[int, Field(ge=0)] | None
    unknown_orders: Annotated[int, Field(ge=0)] | None


class Supervision(Wire):
    status: Literal["READY", "STOPPED", "UNKNOWN"]
    reason: Identity
    next_action: Identity


class Action(Wire):
    operation: OperationName
    target: Identity
    label: Identity
    impact: Identity
    context: Fingerprint
    protective: bool


class Snapshot(Wire):
    api: Literal["console/v1"]
    release: Literal["0.4.0"]
    server_time: Instant
    context: Context
    components: list[Component]
    financial: Financial | None
    supervision: Supervision
    blocker: Identity
    actions: list[Action]
    atomic: Literal[False]


class Session(Wire):
    api: Literal["console/v1"]
    release: Literal["0.4.0"]
    bundle: Fingerprint | None
    actor: Identity
    role: Literal["reader", "operator"]
    csrf: Fingerprint
    identity: Fingerprint
    server_time: Instant
    valid_until: Instant


class ActionCatalog(Wire):
    actions: list[Action]


class PreviewRequest(Wire):
    operation: OperationName
    target: Identity
    context: Fingerprint
    identity: Fingerprint


class Preview(Wire):
    preview_id: Fingerprint
    actor: Identity
    operation: Identity
    target: Identity
    context: Fingerprint
    identity: Fingerprint
    expected_revision: Annotated[int, Field(ge=0)]
    expires_at: Instant
    impact: Identity


class ApplyRequest(Wire):
    preview_id: Fingerprint
    expected_revision: Annotated[int, Field(ge=0)]
    idempotency_key: Annotated[str, Field(pattern=r"^[a-zA-Z0-9-]{16,80}$")]
    context: Fingerprint
    identity: Fingerprint


class Receipt(Wire):
    idempotency_key: Identity
    operation: Identity
    target: Identity
    revision: Annotated[int, Field(ge=1)]
    phase: Literal["REQUESTED", "CLAIMED", "APPLIED", "FAILED", "BLOCKED"]
    effect: Literal["NOT_OBSERVED", "OBSERVED", "UNKNOWN"]
    reason: Identity | None


class Receipts(Wire):
    items: list[Receipt]
    next_cursor: str | None


class Record(Wire):
    identity: Identity
    kind: Literal["wallet", "order"]
    state: Identity
    reason: Identity | None
    side: Literal["BUY", "SELL"] | None
    token: Identity | None
    order_id: Identity | None
    quantity: Money | None
    price: Money | None
    updated_at: Instant | None
    fill_state: Identity | None
    settlement_state: Identity | None


class Page(Wire):
    generation: Fingerprint
    items: Annotated[list[Record], Field(max_length=100)]
    total: Annotated[int, Field(ge=0)]
    next_cursor: str | None


class Detail(Wire):
    generation: Fingerprint
    record: Record
    trace: Literal["Only retained producer links are shown; missing causal links remain UNKNOWN."]


CONTRACT_MODELS = (Snapshot, Session, ActionCatalog, Preview, Receipt, Receipts, Page, Detail)
