"""Occurrence identity is source-neutral and never transaction-only."""

from dataclasses import replace
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from polysia.domain.financial_session import InstrumentScope, SourceOccurrence


@given(st.integers(min_value=0, max_value=2**64 - 1), st.text(min_size=1, max_size=40))
def test_same_occurrence_from_another_source_preserves_identity(index: int, source: str) -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    event = SourceOccurrence(
        "chain",
        "transaction",
        str(index),
        "wallet",
        InstrumentScope("market", "token", "collateral", "route"),
        "BUY",
        now,
        now,
        now,
        "native",
        "source-row",
        "schema-v2",
        True,
        True,
    )
    assert replace(event, source=source, source_key="provider-alias").identity == event.identity
    assert replace(event, occurrence=str(index + 1)).identity != event.identity
    assert replace(event, wallet="different-wallet").identity != event.identity
    # Provider mapping disagreements identify the same occurrence and must be
    # rejected as conflicts, rather than authorize a second economic action.
    assert replace(event, side="SELL").identity == event.identity


@given(
    st.decimals(
        min_value="0.000001", max_value="1000", places=6, allow_nan=False, allow_infinity=False
    )
)
def test_identity_never_depends_on_provider_price_serialization(price: object) -> None:
    from decimal import Decimal

    now = datetime(2026, 10, 25, tzinfo=UTC)
    event = SourceOccurrence(
        "chain",
        "transaction",
        "canonical-log-7",
        "wallet",
        InstrumentScope("market", "token", "collateral", "route"),
        "BUY",
        now,
        now,
        now,
        "native",
        "row",
        "v2",
        True,
        True,
        Decimal(str(price)),
    )
    assert replace(event, leader_price=None, source="polycop").identity == event.identity
