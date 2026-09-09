from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polysia.backtesting.prospective_economics import evaluate_prospective_economics
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
    payload_digest,
)
from polysia.domain.research_evidence.replay import replay_same_observations

START = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _event(
    evidence_id: str,
    *,
    observed_at: datetime,
    kind: ObservationKind,
    side: str,
    price: str,
    size: str,
    levels: tuple[tuple[str, str], ...] = (),
) -> CanonicalResearchEvent:
    wallet = kind is ObservationKind.WALLET_TRADE
    provenance: dict[str, object] = {}
    if not wallet:
        provenance = {
            "book_levels": [
                {"price": level_price, "size": level_size}
                for level_price, level_size in levels
            ],
            "execution_evidence": True,
            "execution_evidence_version": "order-book-depth-v1",
            "fee_calculation_version": "polymarket-taker-fee-v1",
            "fee_exponent": "0",
            "fee_rate": "0",
            "fee_taker_only": True,
            "fees_enabled": False,
        }
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="wallet" if wallet else "market",
        event_kind=kind,
        classification=EvidenceClassification.ACCEPTED,
        market_reference="market-a",
        outcome_reference="token-a",
        side=side,
        price=Decimal(price),
        size=Decimal(size),
        source_time=observed_at - timedelta(milliseconds=100),
        observed_time=observed_at,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=(
            AttributionStatus.WALLET_ALIASED
            if wallet
            else AttributionStatus.NOT_APPLICABLE
        ),
        leader_alias="pub-wallet" if wallet else None,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance=provenance,
        source_event_id=evidence_id if wallet else None,
        run_id="run-1",
    )


def test_economic_report_is_cost_aware_deterministic_and_policy_comparable() -> None:
    wallet_events = tuple(
        _event(
            f"buy-{index}",
            observed_at=START + timedelta(seconds=index * 2),
            kind=ObservationKind.WALLET_TRADE,
            side="BUY",
            price="0.50",
            size="10",
        )
        for index in range(20)
    )
    buy_books = tuple(
        _event(
            f"book-buy-{index}",
            observed_at=START + timedelta(seconds=index * 2 - 1),
            kind=ObservationKind.MARKET_STATE,
            side="BUY",
            price="0.40",
            size="100",
            levels=(("0.40", "100"),),
        )
        for index in range(20)
    )
    sell = _event(
        "sell",
        observed_at=START + timedelta(seconds=50),
        kind=ObservationKind.WALLET_TRADE,
        side="SELL",
        price="0.60",
        size="10",
    )
    sell_book = _event(
        "book-sell",
        observed_at=START + timedelta(seconds=49),
        kind=ObservationKind.MARKET_STATE,
        side="SELL",
        price="0.60",
        size="300",
        levels=(("0.60", "300"),),
    )
    events = (*wallet_events, sell, *buy_books, sell_book)
    replay = replay_same_observations(events, snapshots=(*buy_books, sell_book))

    first = evaluate_prospective_economics(replay, events=events)
    second = evaluate_prospective_economics(replay, events=events)

    assert first.digest == second.digest
    assert first.economic_classification == "POSITIVE"
    assert first.evaluated_observations == 21
    assert first.target.net_pnl is not None and first.target.net_pnl > Decimal("0")
    assert first.control.net_pnl is not None and first.control.net_pnl > first.target.net_pnl
    assert first.target.remaining_positions == ()
    assert first.market_only == "UNSUPPORTED"
    assert first.placebo == "UNSUPPORTED"


def test_legacy_quote_never_becomes_complete_economic_evidence() -> None:
    wallet = _event(
        "wallet",
        observed_at=START,
        kind=ObservationKind.WALLET_TRADE,
        side="BUY",
        price="0.50",
        size="10",
    )
    legacy = _event(
        "legacy",
        observed_at=START - timedelta(seconds=1),
        kind=ObservationKind.MARKET_STATE,
        side="BUY",
        price="0.50",
        size="10",
    )
    legacy.provenance.clear()
    legacy.provenance.update({"execution_evidence": True, "recorded_fee": "0"})
    replay = replay_same_observations((wallet,), snapshots=(legacy,))

    report = evaluate_prospective_economics(replay, events=(wallet, legacy))

    assert report.economic_classification == "INSUFFICIENT_DATA"
    assert report.execution_evidence_ratio == Decimal("0")
    assert dict(report.unknown_by_cause) == {"legacy_incomplete_execution": 1}
