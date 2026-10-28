"""Existing LiveBroker bridge. No credentials, client creation, CLI, or activation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal

from polysia.application.ports.financial_session import RequestCharge, SessionSubmitReceipt
from polysia.config.settings import TradingMode
from polysia.domain.financial_session import (
    AccountObservation,
    ApprovedSessionLimit,
    InstrumentScope,
    SessionBlocked,
    SessionOpportunity,
    digest,
)
from polysia.execution.live_broker import LiveBroker, LiveOrderRejectedError
from polysia.risk.evidence import VerifiedLiveRiskSnapshot


class LiveSessionExecution:
    """A trusted composition root must supply complete, exact-account reads.

    The injected reader owns pagination, balances, fee completeness and venue
    mapping. Legacy source-type identity and daily cashflow do not qualify.
    This bridge never creates account access or run authority by itself.
    """

    def __init__(
        self,
        broker: LiveBroker,
        *,
        account_reader: Callable[[InstrumentScope], Awaitable[AccountObservation]],
        charges: Mapping[str, RequestCharge],
        acknowledgement: bool,
        clock: Callable[[], datetime],
        max_evidence_age_ms: int,
        protective_eligibility: Callable[[str], Awaitable[bool]],
    ) -> None:
        if acknowledgement is not True or set(charges) != {
            "ACCOUNT",
            "SUBMIT",
            "CANCEL",
            "CANCELLATION_READ",
        }:
            raise SessionBlocked("explicit_account_access_and_request_bounds_required")
        self.broker, self.account_reader = broker, account_reader
        self.charges = dict(charges)
        self.clock, self.max_evidence_age_ms = clock, max_evidence_age_ms
        self.protective_eligibility = protective_eligibility
        if max_evidence_age_ms <= 0:
            raise SessionBlocked("positive_evidence_age_required")

    def charge_bound(self, action: str) -> RequestCharge:
        return self.charges[action]

    async def observe_account(self, instrument: InstrumentScope) -> AccountObservation:
        return await self.account_reader(instrument)

    async def submit(
        self,
        approved: ApprovedSessionLimit,
        opportunity: SessionOpportunity,
        snapshot: VerifiedLiveRiskSnapshot,
        *,
        before_submit: Callable[[], None],
        refresh: Callable[[], Awaitable[VerifiedLiveRiskSnapshot]],
        edge: Decimal,
    ) -> SessionSubmitReceipt:
        request = approved.request
        intent = request.as_intent()
        context = snapshot.to_risk_context(
            trading_mode=TradingMode.LIVE,
            live_trading_enabled=True,
            now=self.clock(),
            max_stale_data_age_ms=self.max_evidence_age_ms,
            edge=edge,
        )
        try:
            result = await self.broker.place_limit_order(
                intent,
                context,
                i_understand_this_places_real_orders=True,
                dry_run=False,
                expiration=request.expiration,
                post_only=request.post_only,
                approved_limit=approved,
                verified_state=snapshot,
                refresh_verified_state=refresh,
                before_submit=before_submit,
            )
        except LiveOrderRejectedError as error:
            return SessionSubmitReceipt(None, True, digest(("venue_rejected", error.code)))
        response = result.response
        if isinstance(response, Mapping):
            order_id = response.get("order_id") or response.get("orderID")
        else:
            order_id = getattr(response, "order_id", None)
        return SessionSubmitReceipt(
            order_id if isinstance(order_id, str) and order_id else None,
            False,
            digest(("submit_ack", order_id)),
        )

    async def cancel(self, order_id: str, *, before_cancel: Callable[[], None]) -> None:
        if await self.protective_eligibility(order_id) is not True:
            raise SessionBlocked("venue_protective_cancellation_ineligible")
        await self.broker.cancel_order(
            order_id=order_id,
            i_understand_this_modifies_live_orders=True,
            dry_run=False,
            before_cancel=before_cancel,
        )
