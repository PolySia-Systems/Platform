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
    Financial,
    Money,
    Page,
    Record,
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
        self._records: dict[str, dict[str, Record]] = {"wallet": {}, "order": {}}
        self._indexed = False

    def _index(self) -> None:
        if self._indexed:
            return
        self._records = {"wallet": {}, "order": {}}
        identity = evidence_object((self.financial_raw or {}).get("identity", {}))
        diagnostic = evidence_object(self.publication.get("diagnostic", {}))
        wallets = evidence_object(diagnostic.get("discovery", {})).get("candidates", [])
        # E2 session publications use the retained selection owner.
        wallets = wallets or evidence_object(self.publication.get("selection", {})).get(
            "candidates", []
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
                },
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
                },
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
            value = Financial(
                status=raw.get("status", "UNKNOWN"),
                authority=authority.get("status", "UNKNOWN"),
                authority_until=authority.get("expires_at"),
                reconciliation=exposure.get("reconciliation", "UNKNOWN"),
                economics=evidence_object(raw.get("economics", {})).get("status", "UNKNOWN"),
                cash=self._amount(
                    exposure.get("cash"), identity.get("currency"), "Reconciled cash"
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
    ) -> Page:
        self._index()
        if (
            kind not in self._records
            or not 1 <= limit <= 100
            or len(query) > 128
            or len(state) > 64
            or sort not in {"identity", "-identity"}
        ):
            raise ValueError("invalid_bounded_query")
        binding = fingerprint((kind, query, state, sort, limit))
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
            if query.casefold() in row.identity.casefold() and (not state or state == row.state)
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
            items=rows[offset:end],
            total=len(rows),
            next_cursor=next_cursor,
        )

    def detail(self, kind: str, identity: str, generation: str) -> Detail:
        if generation != self.generation:
            raise LookupError("cursor_expired")
        self._index()
        if kind not in self._records or identity not in self._records[kind]:
            raise KeyError("record_missing")
        return Detail(
            generation=self.generation,
            record=self._records[kind][identity],
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
