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
OperationName = Literal[
    "shadow.create",
    "shadow.clone",
    "shadow.start",
    "shadow.drain",
    "shadow.resume",
    "shadow.finalize",
    "shadow.archive",
    "shadow.compare",
    "policy.stage",
    "session.stop",
    "session.drain",
    "acquisition.stop",
    "acquisition.drain",
    "acquisition.resume",
    "acquisition.export",
]


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
    name: Literal["publication", "financial", "supervision", "worker", "publisher"]
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
    account_observed_at: Instant | None = None
    account_valid_until: Instant | None = None


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
    arguments: Annotated[list[Argument], Field(max_length=2)] = Field(default_factory=list)


class Choice(Wire):
    value: Identity
    label: Identity


class Argument(Wire):
    name: Literal["policy_digest", "source", "other", "start", "end"]
    label: Identity
    kind: Literal["choice", "utc"]
    choices: Annotated[list[Choice], Field(max_length=64)]


class Fact(Wire):
    label: Identity
    value: Annotated[str, Field(max_length=2048)] | None


class EvidenceTable(Wire):
    title: Identity
    columns: Annotated[list[Identity], Field(max_length=12)]
    rows: Annotated[
        list[Annotated[list[Annotated[str, Field(max_length=2048)] | None], Field(max_length=12)]],
        Field(max_length=100),
    ]
    total: Annotated[int, Field(ge=0)] | None
    state: Validity


class EvidenceSection(Wire):
    title: Identity
    validity: Component
    facts: Annotated[list[Fact], Field(max_length=80)]
    tables: Annotated[list[EvidenceTable], Field(max_length=12)]
    guidance: Annotated[str, Field(max_length=2048)]


class Workspace(Wire):
    generation: Fingerprint
    sections: Annotated[list[EvidenceSection], Field(max_length=12)]


class Snapshot(Wire):
    api: Literal["console/v1"]
    release: Literal["0.4.0"]
    server_time: Instant
    context: Context
    components: list[Component]
    financial: Financial | None
    supervision: Supervision
    blocker: Identity
    actions: Annotated[list[Action], Field(max_length=128)]
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
    actions: Annotated[list[Action], Field(max_length=128)]


class PreviewRequest(Wire):
    operation: OperationName
    target: Identity
    context: Fingerprint
    identity: Fingerprint
    arguments: dict[str, Annotated[str, Field(max_length=128)]] = Field(
        default_factory=dict, max_length=2
    )


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
    arguments: list[Fact] = Field(default_factory=list)


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
    download: Annotated[str, Field(pattern=r"^/reports/[a-f0-9]{64}\.json$")] | None = None
    facts: Annotated[list[Fact], Field(max_length=12)] = Field(default_factory=list)
    tables: Annotated[list[EvidenceTable], Field(max_length=2)] = Field(default_factory=list)


class Receipts(Wire):
    items: list[Receipt]
    next_cursor: str | None


class Record(Wire):
    identity: Identity
    kind: Literal["wallet", "order", "position"]
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
    sources: Annotated[list[Identity], Field(max_length=64)] = Field(default_factory=list)
    facts: Annotated[list[Fact], Field(max_length=80)] = Field(default_factory=list)
    links: Annotated[list[RecordLink], Field(max_length=100)] = Field(default_factory=list)


class RecordLink(Wire):
    kind: Literal["wallet", "order", "position"]
    identity: Identity
    label: Identity


class Page(Wire):
    generation: Fingerprint
    items: Annotated[list[Record], Field(max_length=100)]
    total: Annotated[int, Field(ge=0)]
    next_cursor: str | None


class Detail(Wire):
    generation: Fingerprint
    record: Record
    trace: Literal["Only retained producer links are shown; missing causal links remain UNKNOWN."]


Action.model_rebuild()
Record.model_rebuild()
CONTRACT_MODELS = (
    Snapshot,
    Session,
    ActionCatalog,
    Preview,
    Receipt,
    Receipts,
    Page,
    Detail,
    Workspace,
)
