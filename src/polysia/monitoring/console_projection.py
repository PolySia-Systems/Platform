"""Bounded, disposable projections over redacted publications only. No private I/O."""

from __future__ import annotations

import base64
import hashlib
import json
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import ValidationError

from polysia.monitoring.console_contract import (
    Component,
    Context,
    Detail,
    Fact,
    Financial,
    Money,
    Page,
    Record,
    RecordLink,
    Scope,
    Supervision,
)

UNKNOWN_SCOPE = Scope(run=None, account=None, venue=None)


def evidence_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("evidence_object_required")
    return value


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def component(
    name: str,
    raw: dict[str, Any] | None,
    *,
    now: datetime,
    generation: str | None,
    scope: Scope,
    ttl: int = 60,
) -> Component:
    observed, until, state, reason = None, None, "UNAVAILABLE", "evidence_missing"
    if raw is not None:
        try:
            stamp = (
                raw.get("as_of")
                or raw.get("published_at")
                or raw.get("observed_at")
                or raw.get("checked_at")
                or raw.get("at")
            )
            if not isinstance(stamp, str):
                raise ValueError("missing_time")
            parsed = datetime.fromisoformat(stamp)
            if parsed.utcoffset() != timedelta(0) or parsed > now + timedelta(seconds=5):
                raise ValueError("invalid_time")
            end = parsed + timedelta(seconds=ttl)
            # Producer expiry can shorten validity, never extend a local bound.
            if raw.get("expires_at"):
                expiry = datetime.fromisoformat(raw["expires_at"])
                if expiry.utcoffset() != timedelta(0):
                    raise ValueError("invalid_expiry")
                end = min(end, expiry)
            observed, until = parsed.isoformat(), end.isoformat()
            state = "AVAILABLE" if now < end else "STALE"
            reason = "independently_dated_evidence" if state == "AVAILABLE" else "evidence_expired"
        except ValueError, TypeError:
            state, reason = "INCOMPATIBLE", "producer_time_missing_or_invalid"
    return Component.model_validate(
        dict(
            name=name,
            state=state,
            observed_at=observed,
            valid_until=until,
            generation=generation,
            scope=scope,
            reason=reason,
        )
    )


class ConsoleReadModel:
    """At most one generation cached by the gateway; indexes never enter the browser."""

    def __init__(self, publication: dict[str, Any], generation: str) -> None:
        self.publication, self.generation = publication, generation
        self.financial_raw = publication.get("financial_session")
        if not isinstance(self.financial_raw, dict):
            self.financial_raw = None
        identity = evidence_object((self.financial_raw or {}).get("identity", {}))
        self.scope = Scope.model_validate(
            {key: identity.get(key) for key in ("run", "account", "venue")}
        )
        self._records: dict[str, dict[str, Record]] = {"wallet": {}, "order": {}, "position": {}}
        self._indexed = False
        self._wallet_rows: dict[str, dict[str, Any]] = {}
        self._wallet_links: dict[str, list[RecordLink]] = {}
        self._search_text: dict[tuple[str, str], str] = {}

    def _index(self) -> None:
        if self._indexed:
            return
        self._records = {"wallet": {}, "order": {}, "position": {}}
        self._wallet_rows, self._wallet_links, self._search_text = {}, {}, {}
        identity = evidence_object((self.financial_raw or {}).get("identity", {}))
        diagnostic = evidence_object(self.publication.get("diagnostic", {}))
        selection = evidence_object(self.publication.get("selection", {}))
        # An explicit empty selection is authoritative; do not revive stale discovery rows.
        wallets = (
            selection["records"]
            if "records" in selection
            else selection["candidates"]
            if "candidates" in selection
            else evidence_object(diagnostic.get("discovery", {})).get("candidates", [])
        )
        if not isinstance(wallets, list):
            raise ValueError("wallet_records_array_required")
        for row in wallets:
            row = evidence_object(row)
            self._add(
                "wallet",
                {
                    "identity": row.get("wallet_id"),
                    "kind": "wallet",
                    "state": row.get("state", "UNKNOWN"),
                    "reason": ", ".join(row.get("exclusions", []))[:256] or None,
                    "side": None,
                    "token": None,
                    "order_id": None,
                    "quantity": None,
                    "price": None,
                    "updated_at": row.get("last_qualifying_activity"),
                    "fill_state": None,
                    "settlement_state": None,
                    "sources": row.get("sources", [])[:64],
                    "facts": [],
                },
            )
            key = str(row["wallet_id"])
            self._wallet_rows[key] = row
            self._search_text[("wallet", key)] += (
                " "
                + " ".join(
                    str(row.get(field, ""))
                    for field in (
                        "ranking_explanation",
                        "reasons",
                        "exclusions",
                        "execution_eligibility",
                        "eligibility",
                    )
                ).casefold()
            )
        orders = (self.financial_raw or {}).get("orders", [])
        if not isinstance(orders, list):
            raise ValueError("order_records_array_required")
        for row in orders:
            row = evidence_object(row)
            self._add(
                "order",
                {
                    "identity": row.get("intent_id"),
                    "kind": "order",
                    "state": row.get("state", "UNKNOWN"),
                    "reason": row.get("reason") or None,
                    "side": row.get("side"),
                    "token": row.get("token"),
                    "order_id": row.get("order_id"),
                    "updated_at": row.get("updated_at"),
                    "quantity": self._amount(
                        row.get("shares"), "shares", "Approved order quantity"
                    ),
                    "price": self._amount(
                        row.get("price"), identity.get("currency"), "Limit price per share"
                    ),
                    "fill_state": row.get("fill_state", "UNKNOWN"),
                    "settlement_state": row.get("settlement_state", "UNKNOWN"),
                    "facts": [
                        Fact(
                            label=name.replace("_", " "),
                            value=str(row[name])[:2048] if row.get(name) is not None else None,
                        ).model_dump()
                        for name in (
                            "wallet",
                            "policy_digest",
                            "reservation",
                            "trigger_id",
                            "evidence_digest",
                        )
                    ]
                    + [
                        Fact(
                            label="Risk " + name,
                            value=str(evidence_object(row.get("risk", {})).get(name, "UNKNOWN")),
                        ).model_dump()
                        for name in ("approved", "reason")
                    ]
                    + [
                        Fact(label="Timeline " + name, value=str(value)).model_dump()
                        for name, value in list(evidence_object(row.get("timeline", {})).items())[
                            :20
                        ]
                    ]
                    + [
                        Fact(
                            label="Fill " + str(fill.get("fill_id", "UNKNOWN"))[:128],
                            value=" · ".join(
                                f"{name}: {fill.get(name, 'UNKNOWN')}"
                                for name in ("shares", "price", "fee", "confirmed_at")
                            )[:2048],
                        ).model_dump()
                        for fill in row.get("fills", [])[:30]
                    ],
                    "links": [
                        RecordLink(
                            kind="wallet", identity=row["wallet"], label="Retained source wallet"
                        ).model_dump()
                    ]
                    if row.get("wallet") in self._records["wallet"]
                    else [],
                },
            )
        for row in (self.financial_raw or {}).get("positions", []):
            row = evidence_object(row)
            self._add(
                "position",
                dict(
                    identity=row["token"],
                    kind="position",
                    state=row.get("state", "UNKNOWN"),
                    reason=None,
                    side=None,
                    token=row["token"],
                    order_id=None,
                    quantity=self._amount(
                        row.get("shares"),
                        "shares",
                        "Confirmed inventory; uncertainty stays UNKNOWN",
                    ),
                    price=self._amount(
                        row.get("average_price"),
                        identity.get("currency"),
                        "Average accounted price per share",
                    ),
                    updated_at=row.get("updated_at"),
                    fill_state=None,
                    settlement_state="OBSERVED_CASH"
                    if row.get("cash_events")
                    else "UNSETTLED_OR_UNKNOWN",
                    facts=[
                        Fact(
                            label=name.replace("_", " "),
                            value=str(row[name])[:2048] if row.get(name) is not None else None,
                        )
                        for name in ("mark", "valuation_method", "redeemable")
                    ]
                    + [
                        Fact(
                            label="Settled cash " + str(event.get("event_id", "UNKNOWN"))[:128],
                            value=str(event.get("confirmed_cash", "UNKNOWN"))
                            + " "
                            + str(identity.get("currency", "UNKNOWN")),
                        )
                        for event in row.get("cash_events", [])[:30]
                    ],
                    links=[
                        RecordLink(kind="order", identity=key, label="Retained order")
                        for key in row.get("orders", [])[:100]
                    ],
                ),
            )
        for row in orders:
            wallet = row.get("wallet")
            if isinstance(wallet, str):
                self._wallet_links.setdefault(wallet, []).append(
                    RecordLink(
                        kind="order", identity=row["intent_id"], label="Retained decision and order"
                    )
                )
        for key, record in self._records["order"].items():
            if record.token in self._records["position"]:
                self._records["order"][key] = record.model_copy(
                    update={
                        "links": [
                            *record.links,
                            RecordLink(
                                kind="position", identity=record.token, label="Confirmed inventory"
                            ),
                        ]
                    }
                )
        self._indexed = True

    @staticmethod
    def _amount(value: Any, unit: str | None, meaning: str) -> Money:
        return Money(value=value, unit=unit, meaning=meaning)

    def _add(self, kind: str, row: dict[str, Any]) -> None:
        record = Record.model_validate(row)
        if record.identity in self._records[kind]:
            raise ValueError("duplicate_projection_identity")
        self._records[kind][record.identity] = record
        self._search_text[(kind, record.identity)] = " ".join(
            [
                record.identity,
                record.token or "",
                record.order_id or "",
                record.reason or "",
                *record.sources,
                *(fact.value or "" for fact in record.facts),
            ]
        ).casefold()

    def context(self) -> Context:
        identity = evidence_object((self.financial_raw or {}).get("identity", {}))
        return Context(
            dataset=self.publication.get("dataset_role", "UNKNOWN"),
            environment=identity.get("environment", "UNKNOWN"),
            configured_mode=identity.get("configured_mode", "UNKNOWN"),
            observed_mode=(self.financial_raw or {}).get("trading_mode", "UNKNOWN"),
            scope=self.scope,
            generation=self.generation,
            provenance=self.publication.get("version", "retained-redacted-publication"),
        )

    def financial(self, now: datetime) -> tuple[Financial | None, Component]:
        meta = component(
            "financial", self.financial_raw, now=now, generation=self.generation, scope=self.scope
        )
        if self.financial_raw is None:
            return None, meta
        try:
            raw = self.financial_raw
            exposure = evidence_object(raw.get("exposure", {}))
            identity = evidence_object(raw.get("identity", {}))
            configured, observed = (
                identity.get("configured_mode", "UNKNOWN"),
                raw.get("trading_mode", "UNKNOWN"),
            )
            if configured != "UNKNOWN" and observed != "UNKNOWN" and configured != observed:
                meta = meta.model_copy(
                    update={"state": "INCOMPATIBLE", "reason": "mode_evidence_mismatch"}
                )
            elif self.scope.run is None or self.scope.account is None:
                meta = meta.model_copy(
                    update={"state": "PARTIAL", "reason": "financial_identity_incomplete"}
                )
            authority = evidence_object(raw.get("remaining_authority", {}))
            account_at = raw.get("account_observed_at")
            account_until = raw.get("account_valid_until")
            if (not account_at or not account_until) and meta.state == "AVAILABLE":
                meta = meta.model_copy(
                    update={"state": "PARTIAL", "reason": "account_validity_unknown"}
                )
            elif account_at and account_until:
                account_meta = component(
                    "financial",
                    {"observed_at": account_at, "expires_at": account_until},
                    now=now,
                    generation=self.generation,
                    scope=self.scope,
                )
                if account_meta.state != "AVAILABLE" and meta.state == "AVAILABLE":
                    meta = meta.model_copy(
                        update={
                            "state": account_meta.state,
                            "reason": "account_evidence_not_current",
                        }
                    )
                if account_meta.valid_until and meta.valid_until:
                    meta = meta.model_copy(
                        update={"valid_until": min(meta.valid_until, account_meta.valid_until)}
                    )
            reconciled = exposure.get("reconciliation") == "MATCHED"
            if not reconciled and meta.state == "AVAILABLE":
                meta = meta.model_copy(
                    update={"state": "PARTIAL", "reason": "reconciliation_blocked"}
                )
            value = Financial(
                status=raw.get("status", "UNKNOWN"),
                authority=authority.get("status", "UNKNOWN"),
                authority_until=authority.get("expires_at"),
                reconciliation=exposure.get("reconciliation", "UNKNOWN"),
                economics=evidence_object(raw.get("economics", {})).get("status", "UNKNOWN")
                if reconciled
                else "UNKNOWN_RECONCILIATION_BLOCKED",
                cash=self._amount(
                    exposure.get("cash") if reconciled else None,
                    identity.get("currency"),
                    "Reconciled cash" if reconciled else "Cash unknown until reconciliation",
                ),
                exposure=self._amount(
                    exposure.get("open_exposure"),
                    identity.get("currency"),
                    "Held cost plus pending reservations; not market value",
                ),
                reserved=self._amount(
                    exposure.get("reserved"), identity.get("currency"), "Pending order reservation"
                ),
                positions=exposure.get("positions"),
                unknown_orders=exposure.get("unknown_orders"),
                account_observed_at=account_at,
                account_valid_until=account_until,
            )
            return value, meta
        except ValueError:
            return None, meta.model_copy(
                update={"state": "INCOMPATIBLE", "reason": "invalid_financial_contract"}
            )

    def page(
        self,
        *,
        kind: str,
        query: str = "",
        state: str = "",
        sort: str = "identity",
        limit: int = 50,
        cursor: str = "",
        source: str = "",
    ) -> Page:
        if (
            kind not in self._records
            or not 1 <= limit <= 100
            or len(query) > 128
            or len(state) > 64
            or len(source) > 128
            or sort not in {"identity", "-identity"}
        ):
            raise ValueError("invalid_bounded_query")
        self._index()
        binding = fingerprint((kind, query, state, sort, limit, source))
        offset = 0
        if cursor:
            try:
                if len(cursor) > 512:
                    raise ValueError("cursor_too_long")
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if decoded["generation"] != self.generation:
                    raise LookupError("cursor_expired")
                if decoded["binding"] != binding or type(decoded["offset"]) is not int:
                    raise ValueError("cursor_query_differs")
                offset = decoded["offset"]
                if offset < 0:
                    raise ValueError("cursor_offset_invalid")
            except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("invalid_cursor") from error
        rows = [
            row
            for row in self._records[kind].values()
            if query.casefold() in self._search_text[(kind, row.identity)]
            and (not state or state == row.state)
            and (not source or source in row.sources)
        ]
        rows.sort(key=lambda row: row.identity, reverse=sort == "-identity")
        end = offset + limit
        next_cursor = (
            None
            if end >= len(rows)
            else base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "generation": self.generation,
                        "binding": binding,
                        "offset": end,
                    },
                    separators=(",", ":"),
                ).encode()
            ).decode()
        )
        return Page(
            generation=self.generation,
            # Detailed causal evidence is decoded only for one selected record.
            items=[row.model_copy(update={"facts": [], "links": []}) for row in rows[offset:end]],
            total=len(rows),
            next_cursor=next_cursor,
        )

    def detail(self, kind: str, identity: str, generation: str) -> Detail:
        if generation != self.generation:
            raise LookupError("cursor_expired")
        if kind not in self._records or len(identity) > 256:
            raise KeyError("record_missing")
        self._index()
        if identity not in self._records[kind]:
            raise KeyError("record_missing")
        record = self._records[kind][identity]
        if kind == "wallet":
            from polysia.monitoring.console_workspaces import text

            raw = self._wallet_rows[identity]
            links = self._wallet_links.get(identity, [])
            record = record.model_copy(
                update={
                    "links": links[:100],
                    "facts": [
                        Fact(label=name.replace("_", " "), value=text(raw.get(name)))
                        for name in (
                            "execution_eligibility",
                            "eligibility",
                            "ranking_explanation",
                            "reasons",
                            "exclusions",
                            "rank",
                            "last_qualifying_activity",
                        )
                    ]
                    + [
                        Fact(
                            label="Retained downstream orders (first 100 links)",
                            value=str(len(links)),
                        )
                    ],
                }
            )
        return Detail(
            generation=self.generation,
            record=record,
            trace="Only retained producer links are shown; missing causal links remain UNKNOWN.",
        )


def project_supervision(
    raw: dict[str, Any] | None, *, now: datetime, scope: Scope
) -> tuple[Supervision, Component]:
    receipt_scope = UNKNOWN_SCOPE
    if raw is not None:
        # An invalid optional identity stays UNKNOWN; other components survive.
        with suppress(ValidationError):
            receipt_scope = Scope(run=raw.get("scope"), account=None, venue=None)
    meta = component("supervision", raw, now=now, generation=None, scope=receipt_scope, ttl=15)
    status, reason = "UNKNOWN", meta.reason
    if raw is not None and meta.state == "AVAILABLE":
        if scope.run is None or receipt_scope.run != scope.run:
            meta = meta.model_copy(
                update={"state": "INCOMPATIBLE", "reason": "supervision_scope_mismatch"}
            )
            reason = meta.reason
        elif isinstance(raw.get("status"), str) and raw["status"] in {"SUPERVISED", "STOP"}:
            status = {"SUPERVISED": "READY", "STOP": "STOPPED"}[raw["status"]]
            reason = str(raw.get("reason", "supervisor_receipt"))[:256]
        else:
            meta = meta.model_copy(
                update={"state": "INCOMPATIBLE", "reason": "unknown_supervision_status"}
            )
    return Supervision(
        status=cast(Any, status),
        reason=reason,
        next_action=(
            "Inspect protected supervisor / CLI; "
            "Console cannot grant or restore financial authority."
        ),
    ), meta
